from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..config import CameraConfig, MissingDependencyError
from ..events.clip_manager import EventClipManager
from ..events.schema import EventRecord
from ..ingestion.frame_source import FramePacket
from ..paths import ARTIFACT_ROOT, CONFIG_ROOT, DATA_ROOT
from ..pose.mediapipe_pose import MediaPipePoseExtractor
from ..pose.types import PoseObservation
from ..rules.fall import FallEventEngine
from ..tracking.types import TrackObservation
from ..tracking.yolo_tracker import YoloPersonTracker


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


@dataclass
class BrowserSessionRuntime:
    session_id: str
    camera_label: str
    camera_config: CameraConfig
    tracker: YoloPersonTracker
    pose_extractor: MediaPipePoseExtractor
    fall_engine: FallEventEngine
    clip_manager: EventClipManager
    event_file: object
    frame_index: int = -1
    total_events: int = 0
    track_count: int = 0
    pose_count: int = 0
    event_count: int = 0
    latest_event_id: Optional[str] = None
    latest_event_type: Optional[str] = None
    latest_event_started_at: Optional[str] = None
    latest_confidence: Optional[float] = None
    last_seen_at: Optional[str] = None
    last_seen_monotonic: float = 0.0
    last_error: Optional[str] = None


class BrowserLiveInferenceService:
    def __init__(
        self,
        model_name: str = "yolo11n.pt",
        tracker_name: str = "bytetrack.yaml",
        confidence_threshold: float = 0.25,
        pose_model_path: Path = DATA_ROOT / "models" / "pose_landmarker_full.task",
        pose_min_detection_confidence: float = 0.5,
        pose_min_tracking_confidence: float = 0.5,
        fall_threshold_path: Path = CONFIG_ROOT / "thresholds" / "fall.yaml",
        clip_root: Path = ARTIFACT_ROOT / "clips",
        snapshot_root: Path = ARTIFACT_ROOT / "snapshots",
        event_root: Path = ARTIFACT_ROOT / "events",
        frame_width: int = 960,
        frame_height: int = 540,
        target_fps: int = 4,
        default_session_id: str = "browser_desktop_main",
        default_camera_label: str = "브라우저 카메라",
        online_timeout_seconds: int = 5,
    ) -> None:
        self.model_name = model_name
        self.tracker_name = tracker_name
        self.confidence_threshold = confidence_threshold
        self.pose_model_path = pose_model_path
        self.pose_min_detection_confidence = pose_min_detection_confidence
        self.pose_min_tracking_confidence = pose_min_tracking_confidence
        self.fall_threshold_path = fall_threshold_path
        self.clip_root = clip_root
        self.snapshot_root = snapshot_root
        self.event_root = event_root
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.target_fps = target_fps
        self.default_session_id = default_session_id
        self.default_camera_label = default_camera_label
        self.online_timeout_seconds = online_timeout_seconds
        self._runtimes: Dict[str, BrowserSessionRuntime] = {}

    def infer_jpeg_frame(
        self,
        session_id: str,
        frame_bytes: bytes,
        timestamp_ms: Optional[int] = None,
        camera_label: Optional[str] = None,
    ) -> Dict[str, object]:
        if not frame_bytes:
            raise ValueError("frame_bytes is required")

        runtime = self._ensure_runtime(
            session_id=session_id,
            camera_label=camera_label or "browser camera",
        )

        cv2 = _load_cv2()
        frame_array = self._to_numpy_uint8(frame_bytes)
        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("failed to decode JPEG frame")

        frame = self._resize_frame(cv2, frame)
        runtime.frame_index += 1
        packet = FramePacket(
            frame_index=runtime.frame_index,
            timestamp_ms=int(timestamp_ms or 0),
            frame=frame,
        )
        runtime.clip_manager.on_frame(packet)

        tracks = runtime.tracker.track_frame(
            frame=frame,
            frame_index=packet.frame_index,
            timestamp_ms=packet.timestamp_ms,
        )
        poses: List[PoseObservation] = []
        events: List[EventRecord] = []

        for track in tracks:
            pose = runtime.pose_extractor.extract_from_track(
                frame=frame,
                observation=track,
            )
            if pose is None:
                continue
            poses.append(pose)
            for event in runtime.fall_engine.update(
                camera_id=runtime.camera_config.camera_id,
                observation=track,
                pose_observation=pose,
            ):
                event = runtime.clip_manager.register_event(event)
                runtime.event_file.write(json.dumps(event.to_dict(), ensure_ascii=True) + "\n")
                runtime.event_file.flush()
                runtime.total_events += 1
                events.append(event)

        processed_at = datetime.now(timezone.utc).isoformat()
        runtime.track_count = len(tracks)
        runtime.pose_count = len(poses)
        runtime.event_count = len(events)
        runtime.last_seen_at = processed_at
        runtime.last_seen_monotonic = time.monotonic()
        if events:
            latest_event = events[-1]
            runtime.latest_event_id = latest_event.event_id
            runtime.latest_event_type = latest_event.event_type.value
            runtime.latest_event_started_at = latest_event.started_at.isoformat()
            runtime.latest_confidence = latest_event.confidence

        runtime.last_error = None
        return {
            "session_id": session_id,
            "camera_label": runtime.camera_label,
            "frame_index": packet.frame_index,
            "timestamp_ms": packet.timestamp_ms,
            "source_timestamp_ms": packet.timestamp_ms,
            "image_width": frame.shape[1],
            "image_height": frame.shape[0],
            "tracks": [track.to_dict() for track in tracks],
            "poses": [pose.to_dict() for pose in poses],
            "events": [event.to_dict() for event in events],
            "processing_at": processed_at,
            "last_error": None,
            "total_events": runtime.total_events,
        }

    def get_session_summaries(self) -> List[Dict[str, object]]:
        return [
            {
                "session_id": runtime.session_id,
                "camera_label": runtime.camera_label,
                "frame_index": runtime.frame_index,
                "track_count": runtime.track_count,
                "pose_count": runtime.pose_count,
                "event_count": runtime.event_count,
                "total_events": runtime.total_events,
                "last_seen_at": runtime.last_seen_at,
                "last_error": runtime.last_error,
            }
            for runtime in self._runtimes.values()
        ]

    def get_camera_summaries(self) -> List[Dict[str, object]]:
        runtimes = list(self._runtimes.values())
        if not runtimes:
            return [self._build_camera_summary()]
        return [self._build_camera_summary(runtime) for runtime in runtimes]

    def reset(self, session_id: Optional[str] = None) -> Dict[str, object]:
        if session_id is not None:
            runtime = self._runtimes.pop(session_id, None)
            if runtime is not None:
                self._close_runtime(runtime)
        else:
            for runtime in list(self._runtimes.values()):
                self._close_runtime(runtime)
            self._runtimes.clear()
        return {"reset": True, "session_id": session_id}

    def _ensure_runtime(
        self,
        session_id: str,
        camera_label: str,
    ) -> BrowserSessionRuntime:
        runtime = self._runtimes.get(session_id)
        if runtime is not None:
            runtime.camera_label = camera_label
            return runtime

        camera_id = f"browser_{session_id}"
        camera_config = CameraConfig(
            camera_id=camera_id,
            name=camera_label,
            source_type="browser",
            source="browser",
            enabled=True,
            target_fps=self.target_fps,
            frame_width=self.frame_width,
            frame_height=self.frame_height,
            fall_threshold_profile=camera_id,
        )
        event_file_path = self.event_root / "browser_live_events.jsonl"
        event_file_path.parent.mkdir(parents=True, exist_ok=True)
        event_file = event_file_path.open("a", encoding="utf-8")

        runtime = BrowserSessionRuntime(
            session_id=session_id,
            camera_label=camera_label,
            camera_config=camera_config,
            tracker=YoloPersonTracker(
                model_name=self.model_name,
                tracker_name=self.tracker_name,
                confidence_threshold=self.confidence_threshold,
            ),
            pose_extractor=MediaPipePoseExtractor(
                model_path=self.pose_model_path,
                min_detection_confidence=self.pose_min_detection_confidence,
                min_tracking_confidence=self.pose_min_tracking_confidence,
            ),
            fall_engine=FallEventEngine.from_yaml(
                self.fall_threshold_path,
                profile=camera_id,
            ),
            clip_manager=EventClipManager(
                clip_root=self.clip_root,
                snapshot_root=self.snapshot_root,
                target_fps=self.target_fps,
            ),
            event_file=event_file,
        )
        self._runtimes[session_id] = runtime
        return runtime

    def _build_camera_summary(
        self,
        runtime: Optional[BrowserSessionRuntime] = None,
    ) -> Dict[str, object]:
        session_id = runtime.session_id if runtime is not None else self.default_session_id
        camera_label = runtime.camera_label if runtime is not None else self.default_camera_label
        is_online = bool(
            runtime is not None
            and runtime.last_seen_monotonic > 0
            and (time.monotonic() - runtime.last_seen_monotonic) <= self.online_timeout_seconds
        )

        return {
            "camera_id": session_id,
            "name": camera_label,
            "location": "브라우저 입력",
            "zone_label": "브라우저 카메라",
            "stream_status": "online" if is_online else "standby",
            "status_source": "browser_live",
            "source_type": "browser",
            "live_supported": True,
            "live_frame_url": None,
            "live_stream_url": None,
            "last_seen_at": runtime.last_seen_at if runtime is not None else None,
            "total_events": runtime.total_events if runtime is not None else 0,
            "unreviewed_events": runtime.total_events if runtime is not None else 0,
            "fall_events": runtime.total_events if runtime is not None else 0,
            "wandering_events": 0,
            "latest_event_id": runtime.latest_event_id if runtime is not None else None,
            "latest_event_type": runtime.latest_event_type if runtime is not None else None,
            "latest_event_status": "new"
            if runtime is not None and runtime.latest_event_id is not None
            else "",
            "latest_event_started_at": runtime.latest_event_started_at if runtime is not None else None,
            "latest_confidence": runtime.latest_confidence if runtime is not None else None,
            "preview_snapshot_url": None,
            "preview_clip_url": None,
            "detail_event_url": (
                f"/api/events/{runtime.latest_event_id}"
                if runtime is not None and runtime.latest_event_id is not None
                else None
            ),
            "input_fps": self.target_fps,
            "inference_fps": self.target_fps,
            "processing_delay_ms": None,
            "current_track_count": runtime.track_count if runtime is not None else 0,
            "current_pose_track_count": runtime.pose_count if runtime is not None else 0,
            "last_error": runtime.last_error if runtime is not None else None,
        }

    @staticmethod
    def _resize_frame(cv2: object, frame: object, width: int = 960, height: int = 540) -> object:
        source_height, source_width = frame.shape[:2]
        if source_width == width and source_height == height:
            return frame
        return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)

    @staticmethod
    def _to_numpy_uint8(frame_bytes: bytes) -> object:
        import numpy as np  # type: ignore

        return np.frombuffer(frame_bytes, dtype=np.uint8)

    @staticmethod
    def _close_runtime(runtime: BrowserSessionRuntime) -> None:
        runtime.event_file.close()
        runtime.clip_manager.close()
        runtime.pose_extractor.close()


BrowserLiveSessionService = BrowserLiveInferenceService
