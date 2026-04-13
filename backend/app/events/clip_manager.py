from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, List

from ..config import MissingDependencyError
from ..ingestion.frame_source import FramePacket
from ..video.encoding import transcode_mp4_for_web
from .schema import EventRecord


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


@dataclass
class BufferedFrame:
    frame_index: int
    timestamp_ms: int
    frame: object


@dataclass
class PendingClipJob:
    event: EventRecord
    clip_path: Path
    snapshot_path: Path
    start_timestamp_ms: int
    end_timestamp_ms: int
    frames: List[BufferedFrame]


class EventClipManager:
    def __init__(
        self,
        clip_root: Path,
        snapshot_root: Path,
        target_fps: int,
        pre_event_seconds: float = 3.0,
        post_event_seconds: float = 3.0,
        video_codec: str = "mp4v",
    ):
        self._cv2 = _load_cv2()
        self.clip_root = clip_root
        self.snapshot_root = snapshot_root
        self.target_fps = max(1, int(target_fps))
        self.pre_event_seconds = pre_event_seconds
        self.post_event_seconds = post_event_seconds
        self.video_codec = video_codec
        self._buffer: Deque[BufferedFrame] = deque(
            maxlen=max(1, int(round(self.target_fps * self.pre_event_seconds)) + 1)
        )
        self._pending_jobs: List[PendingClipJob] = []
        self.clip_root.mkdir(parents=True, exist_ok=True)
        self.snapshot_root.mkdir(parents=True, exist_ok=True)

    def on_frame(self, packet: FramePacket) -> None:
        buffered_frame = BufferedFrame(
            frame_index=packet.frame_index,
            timestamp_ms=packet.timestamp_ms,
            frame=packet.frame.copy(),
        )
        self._buffer.append(buffered_frame)

        remaining_jobs = []
        for job in self._pending_jobs:
            if not job.frames or job.frames[-1].frame_index != buffered_frame.frame_index:
                job.frames.append(buffered_frame)

            if buffered_frame.timestamp_ms >= job.end_timestamp_ms:
                self._finalize_job(job)
            else:
                remaining_jobs.append(job)

        self._pending_jobs = remaining_jobs

    def register_event(self, event: EventRecord) -> EventRecord:
        clip_dir = self.clip_root / event.camera_id
        snapshot_dir = self.snapshot_root / event.camera_id
        clip_dir.mkdir(parents=True, exist_ok=True)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        clip_path = clip_dir / f"{event.event_id}.mp4"
        snapshot_path = snapshot_dir / f"{event.event_id}.jpg"
        event.clip_path = str(clip_path)
        event.snapshot_path = str(snapshot_path)

        event_timestamp_ms = self._event_timestamp_ms(event)
        start_timestamp_ms = max(
            0,
            event_timestamp_ms - int(round(self.pre_event_seconds * 1000)),
        )
        frames = list(self._buffer)
        end_timestamp_ms = event_timestamp_ms + int(
            round(self.post_event_seconds * 1000)
        )
        job = PendingClipJob(
            event=event,
            clip_path=clip_path,
            snapshot_path=snapshot_path,
            start_timestamp_ms=start_timestamp_ms,
            end_timestamp_ms=end_timestamp_ms,
            frames=frames,
        )

        if frames:
            self._save_snapshot(job.snapshot_path, frames[-1].frame)

        if frames and frames[-1].timestamp_ms >= end_timestamp_ms:
            self._finalize_job(job)
        else:
            self._pending_jobs.append(job)

        return event

    def close(self) -> None:
        for job in list(self._pending_jobs):
            self._finalize_job(job)
        self._pending_jobs = []

    def _event_timestamp_ms(self, event: EventRecord) -> int:
        if event.source_timestamp_ms is not None:
            return int(event.source_timestamp_ms)
        return int(event.started_at.timestamp() * 1000)

    def _finalize_job(self, job: PendingClipJob) -> None:
        if not job.frames:
            return

        output_frames = self._select_output_frames(job)
        if not output_frames:
            return

        first_frame = output_frames[0].frame
        height, width = first_frame.shape[:2]
        writer = self._cv2.VideoWriter(
            str(job.clip_path),
            self._cv2.VideoWriter_fourcc(*self.video_codec),
            float(self.target_fps),
            (width, height),
        )
        try:
            for buffered_frame in output_frames:
                writer.write(buffered_frame.frame)
        finally:
            writer.release()

        transcode_mp4_for_web(job.clip_path)

        if not job.snapshot_path.exists():
            self._save_snapshot(job.snapshot_path, job.frames[-1].frame)

    def _select_output_frames(self, job: PendingClipJob) -> List[BufferedFrame]:
        if not job.frames:
            return []

        total_frame_count = max(
            1,
            int(round((self.pre_event_seconds + self.post_event_seconds) * self.target_fps)),
        )
        if total_frame_count == 1:
            return [job.frames[-1]]

        frame_interval_ms = 1000.0 / float(self.target_fps)
        ordered_frames = sorted(job.frames, key=lambda frame: (frame.timestamp_ms, frame.frame_index))
        selected_frames: List[BufferedFrame] = []
        cursor = 0

        for frame_offset in range(total_frame_count):
            target_timestamp_ms = job.start_timestamp_ms + (frame_offset * frame_interval_ms)
            while cursor + 1 < len(ordered_frames):
                current_distance = abs(ordered_frames[cursor].timestamp_ms - target_timestamp_ms)
                next_distance = abs(ordered_frames[cursor + 1].timestamp_ms - target_timestamp_ms)
                if next_distance <= current_distance:
                    cursor += 1
                    continue
                break
            selected_frames.append(ordered_frames[cursor])

        return selected_frames

    def _save_snapshot(self, path: Path, frame: object) -> None:
        self._cv2.imwrite(str(path), frame)
