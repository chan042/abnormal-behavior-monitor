from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from ..config import MissingDependencyError
from ..events.schema import EventRecord, EventType
from ..video.encoding import transcode_mp4_for_web


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


@dataclass
class DemoEventSpec:
    event_id: str
    event_type: EventType
    track_id: int
    description: str
    roi_id: str | None
    started_at: datetime
    ended_at: datetime
    confidence: float
    status: str
    clip_name: str


def seed_demo_events(
    camera_id: str,
    event_output_path: Path,
    clip_root: Path,
    snapshot_root: Path,
    width: int = 960,
    height: int = 540,
    fps: int = 8,
) -> Dict[str, object]:
    cv2 = _load_cv2()

    event_output_path.parent.mkdir(parents=True, exist_ok=True)
    clip_dir = clip_root / camera_id
    snapshot_dir = snapshot_root / camera_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now().astimezone().replace(microsecond=0)
    specs = [
        DemoEventSpec(
            event_id=f"{camera_id}_fall_demo_001",
            event_type=EventType.FALL_SUSPECTED,
            track_id=17,
            description="실신 의심: 복도 구간에서 자세가 급격히 붕괴된 뒤 무동작 상태가 지속됨",
            roi_id="ward_corridor_a",
            started_at=now - timedelta(minutes=4, seconds=10),
            ended_at=now - timedelta(minutes=4, seconds=4),
            confidence=0.92,
            status="new",
            clip_name="fall_demo_001.mp4",
        ),
        DemoEventSpec(
            event_id=f"{camera_id}_wandering_demo_001",
            event_type=EventType.WANDERING_SUSPECTED,
            track_id=23,
            description="배회 의심: 동일 복도 ROI 내 반복 왕복과 방향 전환이 지속됨",
            roi_id="ward_corridor_a",
            started_at=now - timedelta(minutes=1, seconds=55),
            ended_at=now - timedelta(minutes=1, seconds=30),
            confidence=0.88,
            status="confirmed",
            clip_name="wandering_demo_001.mp4",
        ),
    ]

    records: List[EventRecord] = []
    for spec in specs:
        clip_path = clip_dir / spec.clip_name
        snapshot_path = snapshot_dir / spec.clip_name.replace(".mp4", ".jpg")
        frames = (
            _render_fall_clip(width=width, height=height, fps=fps)
            if spec.event_type == EventType.FALL_SUSPECTED
            else _render_wandering_clip(width=width, height=height, fps=fps)
        )
        _write_clip(cv2, clip_path, frames, fps=fps)
        _write_snapshot(cv2, snapshot_path, frames[-1])
        records.append(
            EventRecord(
                event_id=spec.event_id,
                camera_id=camera_id,
                track_id=spec.track_id,
                event_type=spec.event_type,
                started_at=spec.started_at,
                ended_at=spec.ended_at,
                confidence=spec.confidence,
                roi_id=spec.roi_id,
                clip_path=str(clip_path),
                snapshot_path=str(snapshot_path),
                description=spec.description,
                status=spec.status,
            )
        )

    with event_output_path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record.to_dict(), ensure_ascii=True) + "\n")

    return {
        "camera_id": camera_id,
        "events_written": len(records),
        "event_output_path": str(event_output_path),
        "clip_root": str(clip_dir),
        "snapshot_root": str(snapshot_dir),
    }


def _write_clip(cv2: object, path: Path, frames: Sequence[object], fps: int) -> None:
    first_frame = frames[0]
    height, width = first_frame.shape[:2]
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(max(fps, 1)),
        (width, height),
    )
    try:
        for frame in frames:
            writer.write(frame)
    finally:
        writer.release()
    transcode_mp4_for_web(path)


def _write_snapshot(cv2: object, path: Path, frame: object) -> None:
    cv2.imwrite(str(path), frame)


def _render_fall_clip(width: int, height: int, fps: int) -> List[object]:
    cv2 = _load_cv2()
    total_frames = fps * 6
    frames = []
    for frame_index in range(total_frames):
        frame = _make_background(width, height)
        _draw_roi_overlay(cv2, frame, width, height)

        if frame_index < fps * 2:
            anchor_x = width * 0.48
            anchor_y = height * 0.62
            body_angle = 90
        elif frame_index < fps * 3:
            progress = (frame_index - fps * 2) / max(fps, 1)
            anchor_x = width * (0.48 + 0.08 * progress)
            anchor_y = height * (0.62 + 0.18 * progress)
            body_angle = 90 - int(75 * progress)
        else:
            anchor_x = width * 0.58
            anchor_y = height * 0.8
            body_angle = 8

        _draw_person(cv2, frame, int(anchor_x), int(anchor_y), angle_degrees=body_angle)
        _draw_header(
            cv2,
            frame,
            title="FALL DEMO",
            subtitle="Pose collapse and no-motion segment",
        )
        frames.append(frame)
    return frames


def _render_wandering_clip(width: int, height: int, fps: int) -> List[object]:
    cv2 = _load_cv2()
    total_frames = fps * 8
    frames = []
    left = int(width * 0.28)
    right = int(width * 0.72)
    positions = _ping_pong_positions(left, right, total_frames)
    for frame_index in range(total_frames):
        frame = _make_background(width, height)
        _draw_roi_overlay(cv2, frame, width, height)
        _draw_person(
            cv2,
            frame,
            positions[frame_index],
            int(height * 0.7),
            angle_degrees=90,
        )
        _draw_header(
            cv2,
            frame,
            title="WANDERING DEMO",
            subtitle="Repeated motion inside ROI corridor",
        )
        frames.append(frame)
    return frames


def _make_background(width: int, height: int) -> object:
    import numpy as np

    frame = np.full((height, width, 3), 238, dtype=np.uint8)
    frame[:, :, 1] = 241
    frame[:, :, 2] = 234
    floor_y = int(height * 0.82)
    frame[floor_y:, :, :] = (206, 212, 214)
    return frame


def _draw_roi_overlay(cv2: object, frame: object, width: int, height: int) -> None:
    x1 = int(width * 0.22)
    y1 = int(height * 0.22)
    x2 = int(width * 0.78)
    y2 = int(height * 0.82)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (74, 130, 103), 2)
    cv2.putText(
        frame,
        "ROI: ward_corridor_a",
        (x1 + 8, y1 - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (48, 88, 70),
        2,
        cv2.LINE_AA,
    )


def _draw_header(cv2: object, frame: object, title: str, subtitle: str) -> None:
    cv2.rectangle(frame, (24, 20), (frame.shape[1] - 24, 92), (255, 255, 255), -1)
    cv2.putText(
        frame,
        title,
        (40, 52),
        cv2.FONT_HERSHEY_DUPLEX,
        0.95,
        (24, 62, 48),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        subtitle,
        (40, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (80, 96, 89),
        1,
        cv2.LINE_AA,
    )


def _draw_person(
    cv2: object,
    frame: object,
    anchor_x: int,
    anchor_y: int,
    angle_degrees: int,
) -> None:
    import math

    angle_radians = math.radians(angle_degrees)
    body_length = 110
    body_dx = int(math.cos(angle_radians) * body_length)
    body_dy = int(math.sin(angle_radians) * body_length)
    shoulder = (anchor_x, anchor_y)
    hip = (anchor_x + body_dx, anchor_y - body_dy)

    head_center = (shoulder[0], shoulder[1] - 26)
    cv2.circle(frame, head_center, 16, (69, 100, 191), -1)
    cv2.line(frame, shoulder, hip, (58, 65, 71), 12)
    cv2.line(frame, shoulder, (shoulder[0] - 18, shoulder[1] + 30), (58, 65, 71), 8)
    cv2.line(frame, shoulder, (shoulder[0] + 18, shoulder[1] + 30), (58, 65, 71), 8)
    cv2.line(frame, hip, (hip[0] - 22, hip[1] + 34), (58, 65, 71), 8)
    cv2.line(frame, hip, (hip[0] + 22, hip[1] + 34), (58, 65, 71), 8)


def _ping_pong_positions(left: int, right: int, total_frames: int) -> List[int]:
    positions: List[int] = []
    direction = 1
    current = left
    step = max((right - left) // 14, 1)
    for _ in range(total_frames):
        positions.append(current)
        current += step * direction
        if current >= right:
            current = right
            direction = -1
        elif current <= left:
            current = left
            direction = 1
    return positions
