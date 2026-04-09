from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional, Union
import time


from ..config import CameraConfig, MissingDependencyError


@dataclass
class FramePacket:
    frame_index: int
    timestamp_ms: int
    frame: object


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


class VideoFrameSource:
    def __init__(self, config: CameraConfig):
        self.config = config
        self._cv2 = _load_cv2()

    def iter_frames(
        self,
        max_frames: Optional[int] = None,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> Generator[FramePacket, None, None]:
        if self.config.source_type not in {"file", "rtsp", "camera"}:
            raise NotImplementedError(
                "Only file, RTSP, and camera sources are supported in the initial pipeline."
            )
        if self.config.source_type in {"rtsp", "camera"} and (
            start_ms is not None or end_ms is not None
        ):
            raise ValueError("start_ms/end_ms are only supported for file sources")

        capture_source = self._capture_source()
        capture = self._cv2.VideoCapture(capture_source)
        if not capture.isOpened():
            raise RuntimeError("Failed to open video source: %s" % capture_source)

        if self.config.source_type == "file" and start_ms is not None:
            capture.set(self._cv2.CAP_PROP_POS_MSEC, float(max(start_ms, 0)))

        source_fps = capture.get(self._cv2.CAP_PROP_FPS) or 0.0
        target_fps = float(self.config.target_fps or 0)
        sample_interval = 1
        if source_fps > 0 and target_fps > 0 and source_fps > target_fps:
            sample_interval = max(1, int(round(source_fps / target_fps)))

        emitted_frames = 0
        source_frame_index = -1
        stream_started_at_ms = int(time.monotonic() * 1000)
        last_emitted_monotonic_ms: Optional[int] = None

        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                source_frame_index += 1
                if source_frame_index % sample_interval != 0:
                    continue

                if self.config.source_type in {"rtsp", "camera"}:
                    now_ms = int(time.monotonic() * 1000)
                    if target_fps > 0 and last_emitted_monotonic_ms is not None:
                        frame_interval_ms = int(round(1000.0 / target_fps))
                        if (now_ms - last_emitted_monotonic_ms) < max(frame_interval_ms, 1):
                            continue
                    timestamp_ms = now_ms - stream_started_at_ms
                    last_emitted_monotonic_ms = now_ms
                else:
                    timestamp_ms = int(
                        capture.get(self._cv2.CAP_PROP_POS_MSEC)
                        or int((emitted_frames / max(target_fps, 1.0)) * 1000.0)
                    )
                    if end_ms is not None and timestamp_ms > end_ms:
                        break

                frame = self._resize_frame(frame)
                yield FramePacket(
                    frame_index=emitted_frames,
                    timestamp_ms=timestamp_ms,
                    frame=frame,
                )

                emitted_frames += 1
                if max_frames is not None and emitted_frames >= max_frames:
                    break
        finally:
            capture.release()

    def _capture_source(self) -> Union[str, int]:
        if self.config.source_type == "file":
            return str(Path(self.config.source))
        if self.config.source_type == "camera":
            source = str(self.config.source).strip()
            if source.isdigit():
                return int(source)
            return source
        return self.config.source

    def _resize_frame(self, frame: object) -> object:
        target_width = max(0, int(self.config.frame_width))
        target_height = max(0, int(self.config.frame_height))
        if target_width <= 0 or target_height <= 0:
            return frame

        frame_height, frame_width = frame.shape[:2]
        if frame_width == target_width and frame_height == target_height:
            return frame

        return self._cv2.resize(
            frame,
            (target_width, target_height),
            interpolation=self._cv2.INTER_AREA,
        )
