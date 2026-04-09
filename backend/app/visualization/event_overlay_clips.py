from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from ..config import MissingDependencyError


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


def attach_overlay_clips(
    overlay_video_path: Path,
    event_log_path: Path,
    output_root: Path,
    pre_event_seconds: float = 3.0,
    post_event_seconds: float = 3.0,
) -> Dict[str, object]:
    cv2 = _load_cv2()
    if not overlay_video_path.exists():
        raise FileNotFoundError(f"Overlay video not found: {overlay_video_path}")
    if not event_log_path.exists():
        raise FileNotFoundError(f"Event log not found: {event_log_path}")

    capture = cv2.VideoCapture(str(overlay_video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Failed to open overlay video: {overlay_video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0.0 or width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Overlay video metadata is invalid")

    updated_payloads: List[Dict[str, object]] = []
    written_count = 0
    try:
        with event_log_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                source_timestamp_ms = payload.get("source_timestamp_ms")
                camera_id = str(payload.get("camera_id", "unknown_camera"))
                event_id = str(payload["event_id"])
                if source_timestamp_ms is None:
                    updated_payloads.append(payload)
                    continue

                clip_dir = output_root / camera_id
                clip_dir.mkdir(parents=True, exist_ok=True)
                overlay_clip_path = clip_dir / f"{event_id}_overlay.mp4"

                start_ms = max(0, int(source_timestamp_ms) - int(pre_event_seconds * 1000))
                end_ms = max(start_ms, int(source_timestamp_ms) + int(post_event_seconds * 1000))
                start_frame = max(0, int((start_ms / 1000.0) * fps))
                end_frame = min(total_frames - 1, int((end_ms / 1000.0) * fps))

                _write_segment(
                    cv2=cv2,
                    capture=capture,
                    output_path=overlay_clip_path,
                    fps=fps,
                    width=width,
                    height=height,
                    start_frame=start_frame,
                    end_frame=end_frame,
                )

                payload["overlay_clip_path"] = str(overlay_clip_path)
                updated_payloads.append(payload)
                written_count += 1
    finally:
        capture.release()

    with event_log_path.open("w", encoding="utf-8") as file:
        for payload in updated_payloads:
            file.write(json.dumps(payload, ensure_ascii=True) + "\n")

    return {
        "event_log_path": str(event_log_path),
        "overlay_video_path": str(overlay_video_path),
        "overlay_event_clips_written": written_count,
        "output_root": str(output_root),
    }


def _write_segment(
    cv2: object,
    capture: object,
    output_path: Path,
    fps: float,
    width: int,
    height: int,
    start_frame: int,
    end_frame: int,
) -> None:
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
        current_frame = start_frame
        while current_frame <= end_frame:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
            current_frame += 1
    finally:
        writer.release()
