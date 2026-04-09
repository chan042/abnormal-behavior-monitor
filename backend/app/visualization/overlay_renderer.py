from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import CameraConfig, MissingDependencyError, load_camera_config
from ..events.schema import EventType
from ..ingestion.frame_source import VideoFrameSource
from ..pose.types import PoseLandmarkRecord, PoseObservation
from ..tracking.types import TrackObservation
from ..video.encoding import transcode_mp4_for_web


POSE_CONNECTIONS: Sequence[Tuple[int, int]] = (
    (11, 12),
    (11, 13),
    (13, 15),
    (12, 14),
    (14, 16),
    (11, 23),
    (12, 24),
    (23, 24),
    (23, 25),
    (24, 26),
    (25, 27),
    (26, 28),
    (27, 29),
    (28, 30),
    (29, 31),
    (30, 32),
)


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


@dataclass
class OverlayEventMarker:
    event_id: str
    track_id: int
    event_type: str
    source_timestamp_ms: int
    confidence: float


def render_overlay_video(
    camera_config_path: Path,
    tracking_log_path: Path,
    output_path: Path,
    pose_log_path: Optional[Path] = None,
    event_log_path: Optional[Path] = None,
    max_frames: Optional[int] = None,
    event_window_seconds: float = 3.0,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> Dict[str, object]:
    camera_config = load_camera_config(camera_config_path)
    return render_overlay_video_for_camera(
        camera_config=camera_config,
        tracking_log_path=tracking_log_path,
        output_path=output_path,
        pose_log_path=pose_log_path,
        event_log_path=event_log_path,
        max_frames=max_frames,
        event_window_seconds=event_window_seconds,
        start_ms=start_ms,
        end_ms=end_ms,
    )


def render_overlay_video_for_camera(
    camera_config: CameraConfig,
    tracking_log_path: Path,
    output_path: Path,
    pose_log_path: Optional[Path] = None,
    event_log_path: Optional[Path] = None,
    max_frames: Optional[int] = None,
    event_window_seconds: float = 3.0,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> Dict[str, object]:
    cv2 = _load_cv2()
    frame_source = VideoFrameSource(camera_config)

    tracking_index = _load_tracking_index(tracking_log_path)
    pose_index = _load_pose_index(pose_log_path) if pose_log_path else {}
    event_markers = (
        _load_event_markers(event_log_path)
        if event_log_path and event_log_path.exists()
        else []
    )
    event_window_ms = int(event_window_seconds * 1000)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    frame_count = 0
    frames_with_tracks = 0
    frames_with_pose = 0
    frames_with_events = 0

    try:
        for packet in frame_source.iter_frames(
            max_frames=max_frames,
            start_ms=start_ms,
            end_ms=end_ms,
        ):
            frame = packet.frame.copy()
            observations = tracking_index.get(packet.frame_index, [])
            pose_by_track = pose_index.get(packet.frame_index, {})
            events = [
                marker
                for marker in event_markers
                if abs(packet.timestamp_ms - marker.source_timestamp_ms) <= event_window_ms
            ]

            if observations:
                frames_with_tracks += 1
            if pose_by_track:
                frames_with_pose += 1
            if events:
                frames_with_events += 1

            self_events_by_track = defaultdict(list)
            for marker in events:
                self_events_by_track[marker.track_id].append(marker)

            for observation in observations:
                track_color = _track_color(observation.track_id)
                _draw_tracking_box(cv2, frame, observation, track_color)
                pose_observation = pose_by_track.get(observation.track_id)
                if pose_observation:
                    _draw_pose_landmarks(cv2, frame, pose_observation, track_color)
                if observation.track_id in self_events_by_track:
                    _draw_event_badge(
                        cv2,
                        frame,
                        observation,
                        self_events_by_track[observation.track_id],
                    )

            _draw_header(
                cv2,
                frame,
                camera_id=camera_config.camera_id,
                frame_index=packet.frame_index,
                timestamp_ms=packet.timestamp_ms,
                track_count=len(observations),
                event_count=len(events),
            )

            if writer is None:
                height, width = frame.shape[:2]
                writer = cv2.VideoWriter(
                    str(output_path),
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    float(max(camera_config.target_fps, 1)),
                    (width, height),
                )
            writer.write(frame)
            frame_count += 1
    finally:
        if writer is not None:
            writer.release()

    transcode_mp4_for_web(output_path)

    return {
        "camera_id": camera_config.camera_id,
        "frames_rendered": frame_count,
        "frames_with_tracks": frames_with_tracks,
        "frames_with_pose": frames_with_pose,
        "frames_with_events": frames_with_events,
        "output_path": str(output_path),
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def _load_tracking_index(path: Path) -> Dict[int, List[TrackObservation]]:
    by_frame: Dict[int, List[TrackObservation]] = defaultdict(list)
    for payload in _read_jsonl(path):
        x1, y1, x2, y2 = payload["bbox"]
        observation = TrackObservation(
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
        by_frame[observation.frame_index].append(observation)
    return by_frame


def _load_pose_index(path: Path) -> Dict[int, Dict[int, PoseObservation]]:
    by_frame: Dict[int, Dict[int, PoseObservation]] = defaultdict(dict)
    for payload in _read_jsonl(path):
        observation = PoseObservation(
            frame_index=int(payload["frame_index"]),
            timestamp_ms=int(payload["timestamp_ms"]),
            track_id=int(payload["track_id"]),
            confidence=float(payload["pose_confidence"]),
            landmarks=[PoseLandmarkRecord(**landmark) for landmark in payload["pose_landmarks"]],
        )
        by_frame[observation.frame_index][observation.track_id] = observation
    return by_frame


def _load_event_markers(
    path: Path,
) -> List[OverlayEventMarker]:
    markers: List[OverlayEventMarker] = []
    for payload in _read_jsonl(path):
        source_timestamp_ms = payload.get("source_timestamp_ms")
        if source_timestamp_ms is None:
            continue
        markers.append(
            OverlayEventMarker(
                event_id=str(payload["event_id"]),
                track_id=int(payload["track_id"]),
                event_type=str(payload["event_type"]),
                source_timestamp_ms=int(source_timestamp_ms),
                confidence=float(payload.get("confidence", 0.0)),
            )
        )
    return markers


def _read_jsonl(path: Path) -> Iterable[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                yield payload


def _draw_tracking_box(
    cv2: object,
    frame: object,
    observation: TrackObservation,
    color: Tuple[int, int, int],
) -> None:
    x1 = int(round(observation.x1))
    y1 = int(round(observation.y1))
    x2 = int(round(observation.x2))
    y2 = int(round(observation.y2))
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

    label = "ID {track_id} {confidence:.2f}".format(
        track_id=observation.track_id,
        confidence=observation.confidence,
    )
    (text_width, text_height), _ = cv2.getTextSize(
        label,
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        2,
    )
    text_y = max(y1 - 10, text_height + 8)
    cv2.rectangle(
        frame,
        (x1, text_y - text_height - 8),
        (x1 + text_width + 10, text_y + 4),
        color,
        -1,
    )
    cv2.putText(
        frame,
        label,
        (x1 + 5, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def _draw_pose_landmarks(
    cv2: object,
    frame: object,
    pose_observation: PoseObservation,
    color: Tuple[int, int, int],
    min_visibility: float = 0.35,
) -> None:
    landmarks = {
        landmark.index: landmark
        for landmark in pose_observation.landmarks
        if landmark.visibility >= min_visibility
    }

    for start_index, end_index in POSE_CONNECTIONS:
        start = landmarks.get(start_index)
        end = landmarks.get(end_index)
        if start is None or end is None:
            continue
        cv2.line(
            frame,
            (int(round(start.x)), int(round(start.y))),
            (int(round(end.x)), int(round(end.y))),
            color,
            2,
        )

    for landmark in landmarks.values():
        cv2.circle(
            frame,
            (int(round(landmark.x)), int(round(landmark.y))),
            3,
            (255, 255, 255),
            -1,
        )
        cv2.circle(
            frame,
            (int(round(landmark.x)), int(round(landmark.y))),
            5,
            color,
            1,
        )


def _draw_event_badge(
    cv2: object,
    frame: object,
    observation: TrackObservation,
    markers: Sequence[OverlayEventMarker],
) -> None:
    event_type = markers[0].event_type
    confidence = max(marker.confidence for marker in markers)
    if event_type == EventType.FALL_SUSPECTED.value:
        label = "FALL ALERT {confidence:.2f}".format(confidence=confidence)
        color = (38, 46, 215)
    else:
        label = "EVENT {confidence:.2f}".format(confidence=confidence)
        color = (23, 113, 230)

    x1 = int(round(observation.x1))
    y1 = int(round(observation.y1))
    (text_width, text_height), _ = cv2.getTextSize(
        label,
        cv2.FONT_HERSHEY_DUPLEX,
        0.65,
        2,
    )
    top = max(10, y1 - 42)
    cv2.rectangle(
        frame,
        (x1, top),
        (x1 + text_width + 12, top + text_height + 12),
        color,
        -1,
    )
    cv2.putText(
        frame,
        label,
        (x1 + 6, top + text_height + 2),
        cv2.FONT_HERSHEY_DUPLEX,
        0.65,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def _draw_header(
    cv2: object,
    frame: object,
    camera_id: str,
    frame_index: int,
    timestamp_ms: int,
    track_count: int,
    event_count: int,
) -> None:
    label = (
        f"{camera_id}  frame={frame_index}  "
        f"t={_format_source_timestamp(timestamp_ms)}  "
        f"tracks={track_count}  events={event_count}"
    )
    cv2.rectangle(frame, (18, 18), (frame.shape[1] - 18, 58), (245, 245, 245), -1)
    cv2.putText(
        frame,
        label,
        (30, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (32, 48, 44),
        2,
        cv2.LINE_AA,
    )


def _track_color(track_id: int) -> Tuple[int, int, int]:
    palette = (
        (48, 139, 214),
        (85, 185, 122),
        (224, 158, 45),
        (179, 89, 201),
        (63, 175, 187),
        (222, 94, 74),
    )
    return palette[track_id % len(palette)]


def _format_source_timestamp(timestamp_ms: int) -> str:
    total_seconds = timestamp_ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    milliseconds = timestamp_ms % 1000
    return "{minutes:02d}:{seconds:02d}.{milliseconds:03d}".format(
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
    )
