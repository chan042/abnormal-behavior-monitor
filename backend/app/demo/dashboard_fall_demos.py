from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from ..config import CameraConfig, MissingDependencyError
from ..evaluation.swoon_dataset import parse_swoon_annotation
from ..events.schema import EventRecord, EventType
from ..ingestion.frame_source import VideoFrameSource
from ..paths import ARTIFACT_ROOT, PROJECT_ROOT
from ..tracking.types import TrackObservation
from ..video.encoding import transcode_mp4_for_web
from ..visualization.overlay_renderer import render_overlay_video_for_camera


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


@dataclass(frozen=True)
class CuratedFallDemoSpec:
    sample_id: str
    started_at: str
    confidence: float = 0.9

    @property
    def event_id(self) -> str:
        return f"dashboard_{self.sample_id}_fall_positive"


@dataclass
class BufferedFrame:
    frame_index: int
    timestamp_ms: int
    frame: object


CURATED_FALL_DEMO_SPECS: Sequence[CuratedFallDemoSpec] = (
    CuratedFallDemoSpec(
        sample_id="101-2_cam01_swoon01_place03_day_spring",
        started_at="2026-04-05T14:53:46.346270+09:00",
        confidence=0.95,
    ),
    CuratedFallDemoSpec(
        sample_id="101-2_cam03_swoon01_place03_day_summer",
        started_at="2026-04-05T14:53:51.157160+09:00",
        confidence=0.94,
    ),
    CuratedFallDemoSpec(
        sample_id="101-2_cam01_swoon01_place03_day_winter",
        started_at="2026-04-05T14:54:00.310819+09:00",
        confidence=0.92,
    ),
    CuratedFallDemoSpec(
        sample_id="101-3_cam01_swoon01_place03_day_winter",
        started_at="2026-04-05T14:54:12.550835+09:00",
        confidence=0.93,
    ),
    CuratedFallDemoSpec(
        sample_id="101-3_cam02_swoon01_place03_day_winter",
        started_at="2026-04-05T14:54:16.444844+09:00",
        confidence=0.91,
    ),
)


def rebuild_dashboard_fall_demos(
    event_output_path: Path = ARTIFACT_ROOT / "events" / "dashboard_samples.jsonl",
    clip_root: Path = ARTIFACT_ROOT / "clips" / "dashboard_samples",
    overlay_root: Path = ARTIFACT_ROOT / "overlays" / "dashboard_samples",
    snapshot_root: Path = ARTIFACT_ROOT / "snapshots" / "dashboard_samples",
    target_fps: int = 5,
    frame_width: int = 1280,
    frame_height: int = 720,
    pre_event_seconds: float = 3.0,
    post_event_seconds: float = 3.0,
) -> Dict[str, object]:
    cv2 = _load_cv2()
    clip_root.mkdir(parents=True, exist_ok=True)
    overlay_root.mkdir(parents=True, exist_ok=True)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    event_output_path.parent.mkdir(parents=True, exist_ok=True)

    records: List[EventRecord] = []
    clips_written = 0
    overlays_written = 0
    snapshots_written = 0

    for spec in CURATED_FALL_DEMO_SPECS:
        source_record = _load_swoon_record(spec.sample_id)
        falldown_start_ms = min(
            action.start_ms for action in source_record.action_segments("falldown")
        )
        segment_id = f"{spec.sample_id}_fall_positive"
        tracking_log_path = (
            ARTIFACT_ROOT
            / "evaluations"
            / "swoon_sample_1_full_eval_baseline"
            / segment_id
            / "logs"
            / "tracking.jsonl"
        )
        pose_log_path = (
            ARTIFACT_ROOT
            / "evaluations"
            / "swoon_sample_1_full_eval_baseline"
            / segment_id
            / "logs"
            / "pose.jsonl"
        )
        anchor_observation = _nearest_track_observation(
            tracking_log_path=tracking_log_path,
            target_timestamp_ms=falldown_start_ms,
        )
        demo_observation = _select_demo_observation(
            tracking_log_path=tracking_log_path,
            anchor_track_id=anchor_observation.track_id,
            window_start_ms=falldown_start_ms,
            window_end_ms=falldown_start_ms + 1500,
        )
        camera_config = CameraConfig(
            camera_id=source_record.camera_id,
            name=spec.sample_id,
            source_type="file",
            source=str((PROJECT_ROOT / source_record.video_path).resolve()),
            enabled=True,
            target_fps=target_fps,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        clip_start_ms = max(
            0,
            demo_observation.timestamp_ms - int(round(pre_event_seconds * 1000)),
        )
        clip_end_ms = demo_observation.timestamp_ms + int(round(post_event_seconds * 1000))
        rendered_frames = _collect_display_frames(
            camera_config=camera_config,
            start_ms=clip_start_ms,
            end_ms=clip_end_ms,
        )
        if not rendered_frames:
            raise RuntimeError(f"No frames extracted for clip: {camera_config.source}")
        event_frame_index = min(
            len(rendered_frames) - 1,
            int(round(pre_event_seconds * max(camera_config.target_fps, 1))),
        )
        demo_event_timestamp_ms = rendered_frames[event_frame_index].timestamp_ms

        observation = _nearest_track_observation(
            tracking_log_path=tracking_log_path,
            target_timestamp_ms=demo_event_timestamp_ms,
        )

        clip_path = clip_root / f"{spec.sample_id}.mp4"
        overlay_path = overlay_root / f"{spec.sample_id}_overlay.mp4"
        snapshot_path = snapshot_root / f"{spec.sample_id}.jpg"

        _write_rendered_frames(
            rendered_frames=rendered_frames,
            output_path=clip_path,
            target_fps=camera_config.target_fps,
        )
        clips_written += 1

        with tempfile.TemporaryDirectory() as tmp_dir_name:
            event_log_path = Path(tmp_dir_name) / "event.jsonl"
            _write_temp_event_log(
                event_log_path=event_log_path,
                event_id=spec.event_id,
                track_id=observation.track_id,
                source_timestamp_ms=demo_event_timestamp_ms,
                confidence=spec.confidence,
            )
            render_overlay_video_for_camera(
                camera_config=camera_config,
                tracking_log_path=tracking_log_path,
                pose_log_path=pose_log_path,
                event_log_path=event_log_path,
                output_path=overlay_path,
                start_ms=clip_start_ms,
                end_ms=clip_end_ms,
            )
        overlays_written += 1

        if _extract_overlay_snapshot(
            cv2=cv2,
            overlay_path=overlay_path,
            output_path=snapshot_path,
            target_frame_index=event_frame_index,
        ):
            snapshots_written += 1

        started_at = datetime.fromisoformat(spec.started_at)
        records.append(
            EventRecord(
                event_id=spec.event_id,
                camera_id=source_record.camera_id,
                track_id=observation.track_id,
                event_type=EventType.FALL_SUSPECTED,
                started_at=started_at,
                ended_at=started_at,
                source_timestamp_ms=demo_event_timestamp_ms,
                confidence=spec.confidence,
                clip_path=str(clip_path.relative_to(PROJECT_ROOT)),
                overlay_clip_path=str(overlay_path.relative_to(PROJECT_ROOT)),
                snapshot_path=str(snapshot_path.relative_to(PROJECT_ROOT)),
                description="실내 공간에서 한 사람이 급격히 무너져 바닥에 쓰러진 자세가 감지되어 실신이 의심됩니다.",
                description_status="fallback",
                description_source="rule",
                status="confirmed",
                details={
                    "target_bbox": [
                        round(observation.x1, 3),
                        round(observation.y1, 3),
                        round(observation.x2, 3),
                        round(observation.y2, 3),
                    ],
                    "phase": "FALL_CONFIRMED",
                    "sample_id": spec.sample_id,
                },
            )
        )

    with event_output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=True) + "\n")

    return {
        "event_output_path": str(event_output_path),
        "events_written": len(records),
        "clips_written": clips_written,
        "overlays_written": overlays_written,
        "snapshots_written": snapshots_written,
    }


def _load_swoon_record(sample_id: str):
    take_id = sample_id.split("_", maxsplit=1)[0]
    xml_path = (
        PROJECT_ROOT
        / "swoon_sample_1"
        / f"{take_id}_swoon01_place03_day"
        / f"{sample_id}.xml"
    )
    return parse_swoon_annotation(xml_path, project_root=PROJECT_ROOT)


def _read_tracking_observations(path: Path) -> Iterable[TrackObservation]:
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            x1, y1, x2, y2 = payload["bbox"]
            yield TrackObservation(
                frame_index=int(payload["frame_index"]),
                timestamp_ms=int(payload["timestamp_ms"]),
                track_id=int(payload["track_id"]),
                class_id=int(payload["class_id"]),
                class_name=str(payload["class_name"]),
                confidence=float(payload["confidence"]),
                x1=float(x1),
                y1=float(y1),
                x2=float(x2),
                y2=float(y2),
            )


def _nearest_track_observation(
    tracking_log_path: Path,
    target_timestamp_ms: int,
) -> TrackObservation:
    nearest: TrackObservation | None = None
    nearest_distance: int | None = None
    nearest_area = -1.0
    for observation in _read_tracking_observations(tracking_log_path):
        distance = abs(observation.timestamp_ms - target_timestamp_ms)
        area = max(0.0, observation.x2 - observation.x1) * max(
            0.0,
            observation.y2 - observation.y1,
        )
        if nearest is None or nearest_distance is None:
            nearest = observation
            nearest_distance = distance
            nearest_area = area
            continue
        if distance < nearest_distance or (distance == nearest_distance and area > nearest_area):
            nearest = observation
            nearest_distance = distance
            nearest_area = area
    if nearest is None:
        raise RuntimeError(f"No tracking observation found: {tracking_log_path}")
    return nearest


def _select_demo_observation(
    tracking_log_path: Path,
    anchor_track_id: int,
    window_start_ms: int,
    window_end_ms: int,
) -> TrackObservation:
    candidates: List[TrackObservation] = []
    for observation in _read_tracking_observations(tracking_log_path):
        if observation.track_id != anchor_track_id:
            continue
        if observation.timestamp_ms < window_start_ms or observation.timestamp_ms > window_end_ms:
            continue
        candidates.append(observation)
    if not candidates:
        return _nearest_track_observation(
            tracking_log_path=tracking_log_path,
            target_timestamp_ms=window_start_ms,
        )

    def sort_key(observation: TrackObservation) -> tuple[float, float, int]:
        width = max(1e-6, observation.x2 - observation.x1)
        height = max(1e-6, observation.y2 - observation.y1)
        ratio = height / width
        area = width * height
        return (ratio, -area, observation.timestamp_ms)

    return min(candidates, key=sort_key)


def _write_rendered_frames(
    rendered_frames: Sequence[BufferedFrame],
    output_path: Path,
    target_fps: int,
) -> None:
    cv2 = _load_cv2()
    if not rendered_frames:
        raise RuntimeError(f"No rendered frames available for clip: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    first_frame = rendered_frames[0].frame
    height, width = first_frame.shape[:2]
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(max(target_fps, 1)),
        (width, height),
    )
    try:
        for frame in rendered_frames:
            writer.write(frame.frame)
    finally:
        writer.release()
    transcode_mp4_for_web(output_path)


def _collect_display_frames(
    camera_config: CameraConfig,
    start_ms: int,
    end_ms: int,
) -> List[BufferedFrame]:
    frame_source = VideoFrameSource(camera_config)
    return [
        BufferedFrame(
            frame_index=packet.frame_index,
            timestamp_ms=packet.timestamp_ms,
            frame=packet.frame,
        )
        for packet in frame_source.iter_frames(
            start_ms=start_ms,
            end_ms=end_ms,
        )
    ]


def _write_temp_event_log(
    event_log_path: Path,
    event_id: str,
    track_id: int,
    source_timestamp_ms: int,
    confidence: float,
) -> None:
    payload = {
        "event_id": event_id,
        "track_id": track_id,
        "event_type": EventType.FALL_SUSPECTED.value,
        "source_timestamp_ms": source_timestamp_ms,
        "confidence": confidence,
    }
    event_log_path.write_text(
        json.dumps(payload, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _extract_overlay_snapshot(
    cv2: object,
    overlay_path: Path,
    output_path: Path,
    target_frame_index: int,
) -> bool:
    capture = cv2.VideoCapture(str(overlay_path))
    if not capture.isOpened():
        return False
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, float(max(target_frame_index, 0)))
        ok, frame = capture.read()
        if not ok:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return bool(cv2.imwrite(str(output_path), frame))
    finally:
        capture.release()
