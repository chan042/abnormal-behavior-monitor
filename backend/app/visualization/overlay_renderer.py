from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

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

OVERLAY_FONT_CANDIDATES: Sequence[Path] = (
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
)


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


def _load_pil():
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except ModuleNotFoundError:
        return None
    return Image, ImageDraw, ImageFont


@lru_cache(maxsize=1)
def _resolve_overlay_font_path() -> Optional[Path]:
    for candidate in OVERLAY_FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


@lru_cache(maxsize=16)
def _load_overlay_font(font_size: int):
    pil_modules = _load_pil()
    if pil_modules is None:
        return None
    _, _, image_font = pil_modules
    font_path = _resolve_overlay_font_path()
    if font_path is None:
        return None
    try:
        return image_font.truetype(str(font_path), font_size)
    except OSError:
        return None


def _measure_overlay_text(text: str, font_size: int) -> Optional[Tuple[object, Tuple[int, int, int, int]]]:
    pil_modules = _load_pil()
    if pil_modules is None:
        return None
    image_class, image_draw_class, _ = pil_modules
    font = _load_overlay_font(font_size)
    if font is None:
        return None

    image = image_class.new("RGB", (8, 8))
    draw = image_draw_class.Draw(image)
    bbox = draw.textbbox((0, 0), text, font=font)
    return font, bbox


def _draw_unicode_text(
    frame: object,
    text: str,
    origin: Tuple[int, int],
    *,
    font: object,
    color: Tuple[int, int, int],
) -> bool:
    pil_modules = _load_pil()
    if pil_modules is None:
        return False
    image_class, image_draw_class, _ = pil_modules

    image = image_class.fromarray(frame[:, :, ::-1])
    draw = image_draw_class.Draw(image)
    draw.text(origin, text, font=font, fill=(color[2], color[1], color[0]))
    frame[:, :] = np.asarray(image)[:, :, ::-1]
    return True


@dataclass
class OverlayEventMarker:
    event_id: str
    track_id: int
    event_type: str
    source_timestamp_ms: int
    confidence: float


@dataclass
class OverlayTrackingIndex:
    by_frame: Dict[int, List[TrackObservation]]
    by_timestamp: Dict[int, List[TrackObservation]]


@dataclass
class OverlayPoseIndex:
    by_frame: Dict[int, Dict[int, PoseObservation]]
    by_timestamp: Dict[int, Dict[int, PoseObservation]]


def marker_from_event(event: object) -> OverlayEventMarker:
    return OverlayEventMarker(
        event_id=str(event.event_id),
        track_id=int(event.track_id),
        event_type=str(event.event_type.value),
        source_timestamp_ms=int(event.source_timestamp_ms or 0),
        confidence=float(event.confidence),
    )


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
    observation_frame_width: Optional[int] = None,
    observation_frame_height: Optional[int] = None,
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
        observation_frame_width=observation_frame_width,
        observation_frame_height=observation_frame_height,
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
    observation_frame_width: Optional[int] = None,
    observation_frame_height: Optional[int] = None,
) -> Dict[str, object]:
    cv2 = _load_cv2()
    frame_source = VideoFrameSource(camera_config)

    tracking_index = _load_tracking_index(tracking_log_path)
    pose_index = (
        _load_pose_index(pose_log_path)
        if pose_log_path
        else OverlayPoseIndex(by_frame={}, by_timestamp={})
    )
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
            observations = tracking_index.by_timestamp.get(packet.timestamp_ms)
            if observations is None:
                observations = tracking_index.by_frame.get(packet.frame_index, [])
            pose_by_track = pose_index.by_timestamp.get(packet.timestamp_ms)
            if pose_by_track is None:
                pose_by_track = pose_index.by_frame.get(packet.frame_index, {})
            events = _active_event_markers(
                event_markers,
                timestamp_ms=packet.timestamp_ms,
                event_window_ms=event_window_ms,
            )

            if observations:
                frames_with_tracks += 1
            if pose_by_track:
                frames_with_pose += 1
            if events:
                frames_with_events += 1

            frame = annotate_frame(
                cv2,
                packet.frame,
                observations=observations,
                pose_by_track=pose_by_track,
                event_markers=events,
                camera_id=camera_config.camera_id,
                frame_index=packet.frame_index,
                timestamp_ms=packet.timestamp_ms,
                include_header=True,
                observation_frame_width=observation_frame_width,
                observation_frame_height=observation_frame_height,
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


def annotate_frame(
    cv2: object,
    frame: object,
    observations: Sequence[TrackObservation],
    pose_by_track: Dict[int, PoseObservation],
    event_markers: Sequence[OverlayEventMarker],
    camera_id: Optional[str] = None,
    frame_index: Optional[int] = None,
    timestamp_ms: Optional[int] = None,
    include_header: bool = True,
    observation_frame_width: Optional[int] = None,
    observation_frame_height: Optional[int] = None,
) -> object:
    annotated = frame.copy()
    scale_x, scale_y = _observation_scale(
        frame,
        observation_frame_width=observation_frame_width,
        observation_frame_height=observation_frame_height,
    )
    scaled_observations = [
        _scale_track_observation(observation, scale_x=scale_x, scale_y=scale_y)
        for observation in observations
    ]
    scaled_pose_by_track = {
        track_id: _scale_pose_observation(
            pose_observation,
            scale_x=scale_x,
            scale_y=scale_y,
        )
        for track_id, pose_observation in pose_by_track.items()
    }
    events_by_track = _group_markers_by_track(event_markers)

    for observation in scaled_observations:
        track_color = _track_color(observation.track_id)
        _draw_tracking_box(cv2, annotated, observation, track_color)
        pose_observation = scaled_pose_by_track.get(observation.track_id)
        if pose_observation:
            _draw_pose_landmarks(cv2, annotated, pose_observation, track_color)
        track_events = events_by_track.get(observation.track_id, [])
        if track_events:
            _draw_event_highlight(cv2, annotated, observation)
            _draw_event_badge(
                cv2,
                annotated,
                observation,
                track_events,
            )

    if include_header and camera_id is not None and frame_index is not None and timestamp_ms is not None:
        _draw_header(
            cv2,
            annotated,
            camera_id=camera_id,
            frame_index=frame_index,
            timestamp_ms=timestamp_ms,
            track_count=len(scaled_observations),
            event_count=len(event_markers),
        )
    return annotated


def write_event_snapshot(
    cv2: object,
    output_path: Path,
    frame: object,
    observations: Sequence[TrackObservation],
    pose_by_track: Dict[int, PoseObservation],
    event_marker: OverlayEventMarker,
    observation_frame_width: Optional[int] = None,
    observation_frame_height: Optional[int] = None,
) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = annotate_frame(
        cv2,
        frame,
        observations=observations,
        pose_by_track=pose_by_track,
        event_markers=[event_marker],
        include_header=False,
        observation_frame_width=observation_frame_width,
        observation_frame_height=observation_frame_height,
    )
    return bool(cv2.imwrite(str(output_path), snapshot))


def _observation_scale(
    frame: object,
    *,
    observation_frame_width: Optional[int],
    observation_frame_height: Optional[int],
) -> Tuple[float, float]:
    frame_height, frame_width = frame.shape[:2]
    if (
        observation_frame_width is None
        or observation_frame_height is None
        or observation_frame_width <= 0
        or observation_frame_height <= 0
    ):
        return 1.0, 1.0

    scale_x = frame_width / float(observation_frame_width)
    scale_y = frame_height / float(observation_frame_height)
    if abs(scale_x - 1.0) < 1e-6 and abs(scale_y - 1.0) < 1e-6:
        return 1.0, 1.0
    return scale_x, scale_y


def _scale_track_observation(
    observation: TrackObservation,
    *,
    scale_x: float,
    scale_y: float,
) -> TrackObservation:
    if abs(scale_x - 1.0) < 1e-6 and abs(scale_y - 1.0) < 1e-6:
        return observation
    return replace(
        observation,
        x1=observation.x1 * scale_x,
        y1=observation.y1 * scale_y,
        x2=observation.x2 * scale_x,
        y2=observation.y2 * scale_y,
    )


def _scale_pose_observation(
    observation: PoseObservation,
    *,
    scale_x: float,
    scale_y: float,
) -> PoseObservation:
    if abs(scale_x - 1.0) < 1e-6 and abs(scale_y - 1.0) < 1e-6:
        return observation
    return replace(
        observation,
        landmarks=[
            replace(
                landmark,
                x=landmark.x * scale_x,
                y=landmark.y * scale_y,
            )
            for landmark in observation.landmarks
        ],
    )


def _load_tracking_index(path: Path) -> OverlayTrackingIndex:
    by_frame: Dict[int, List[TrackObservation]] = defaultdict(list)
    by_timestamp: Dict[int, List[TrackObservation]] = defaultdict(list)
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
        by_timestamp[observation.timestamp_ms].append(observation)
    return OverlayTrackingIndex(
        by_frame=by_frame,
        by_timestamp=by_timestamp,
    )


def _load_pose_index(path: Path) -> OverlayPoseIndex:
    by_frame: Dict[int, Dict[int, PoseObservation]] = defaultdict(dict)
    by_timestamp: Dict[int, Dict[int, PoseObservation]] = defaultdict(dict)
    for payload in _read_jsonl(path):
        observation = PoseObservation(
            frame_index=int(payload["frame_index"]),
            timestamp_ms=int(payload["timestamp_ms"]),
            track_id=int(payload["track_id"]),
            confidence=float(payload["pose_confidence"]),
            landmarks=[PoseLandmarkRecord(**landmark) for landmark in payload["pose_landmarks"]],
        )
        by_frame[observation.frame_index][observation.track_id] = observation
        by_timestamp[observation.timestamp_ms][observation.track_id] = observation
    return OverlayPoseIndex(
        by_frame=by_frame,
        by_timestamp=by_timestamp,
    )


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


def _group_markers_by_track(
    markers: Sequence[OverlayEventMarker],
) -> Dict[int, List[OverlayEventMarker]]:
    grouped: Dict[int, List[OverlayEventMarker]] = defaultdict(list)
    for marker in markers:
        grouped[marker.track_id].append(marker)
    return grouped


def _active_event_markers(
    markers: Sequence[OverlayEventMarker],
    *,
    timestamp_ms: int,
    event_window_ms: int,
) -> List[OverlayEventMarker]:
    return [
        marker
        for marker in markers
        if _is_marker_active(
            marker,
            timestamp_ms=timestamp_ms,
            event_window_ms=event_window_ms,
        )
    ]


def _is_marker_active(
    marker: OverlayEventMarker,
    *,
    timestamp_ms: int,
    event_window_ms: int,
) -> bool:
    offset_ms = timestamp_ms - marker.source_timestamp_ms
    return 0 <= offset_ms <= event_window_ms


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
    event_label = (
        "실신 의심"
        if event_type == EventType.FALL_SUSPECTED.value
        else "배회 의심"
    )
    label = "AI EVENT | {event_label} | {confidence:.2f}".format(
        event_label=event_label,
        confidence=confidence,
    )
    fill_color = (28, 46, 215)
    accent_color = (255, 255, 255)
    font_size = 20

    x1 = int(round(observation.x1))
    y1 = int(round(observation.y1))
    font_metrics = _measure_overlay_text(label, font_size)
    if font_metrics is not None:
        font, text_bbox = font_metrics
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
    else:
        font = None
        (text_width, text_height), _ = cv2.getTextSize(
            label,
            cv2.FONT_HERSHEY_DUPLEX,
            0.58,
            2,
        )
    badge_width = min(
        max(text_width + 14, 360),
        max(80, frame.shape[1] - x1 - 4),
    )
    top = max(10, y1 - 46)
    cv2.rectangle(
        frame,
        (x1, top),
        (x1 + badge_width, top + text_height + 14),
        fill_color,
        -1,
    )
    cv2.rectangle(
        frame,
        (x1, top),
        (x1 + badge_width, top + text_height + 14),
        accent_color,
        2,
    )
    pointer_x = x1 + 18
    pointer_top = top + text_height + 14
    cv2.line(frame, (pointer_x, pointer_top), (x1 + 10, y1 - 4), accent_color, 2)
    if font is not None and font_metrics is not None:
        _draw_unicode_text(
            frame,
            label,
            (
                x1 + 7 - text_bbox[0],
                top + 7 - text_bbox[1],
            ),
            font=font,
            color=(255, 255, 255),
        )
        return
    cv2.putText(
        frame,
        label,
        (x1 + 7, top + text_height + 3),
        cv2.FONT_HERSHEY_DUPLEX,
        0.58,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )


def _draw_event_highlight(
    cv2: object,
    frame: object,
    observation: TrackObservation,
) -> None:
    x1 = int(round(observation.x1))
    y1 = int(round(observation.y1))
    x2 = int(round(observation.x2))
    y2 = int(round(observation.y2))
    color = (28, 46, 215)

    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
    corner = max(12, min((x2 - x1) // 4, (y2 - y1) // 4))
    cv2.line(frame, (x1, y1), (x1 + corner, y1), (255, 255, 255), 2)
    cv2.line(frame, (x1, y1), (x1, y1 + corner), (255, 255, 255), 2)
    cv2.line(frame, (x2, y1), (x2 - corner, y1), (255, 255, 255), 2)
    cv2.line(frame, (x2, y1), (x2, y1 + corner), (255, 255, 255), 2)
    cv2.line(frame, (x1, y2), (x1 + corner, y2), (255, 255, 255), 2)
    cv2.line(frame, (x1, y2), (x1, y2 - corner), (255, 255, 255), 2)
    cv2.line(frame, (x2, y2), (x2 - corner, y2), (255, 255, 255), 2)
    cv2.line(frame, (x2, y2), (x2, y2 - corner), (255, 255, 255), 2)


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
