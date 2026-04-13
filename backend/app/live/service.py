from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from ..config import CameraConfig, MissingDependencyError, load_camera_config
from ..events.clip_manager import EventClipManager
from ..events.schema import EventRecord
from ..events.storage import persist_event_record
from ..ingestion.frame_source import VideoFrameSource
from ..paths import ARTIFACT_ROOT, CONFIG_ROOT, DATA_ROOT
from ..pose.mediapipe_pose import MediaPipePoseExtractor
from ..pose.types import PoseObservation
from ..rules.fall import FallEventEngine
from ..rules.wandering import (
    WanderingEventEngine,
    WanderingThresholds,
    build_full_frame_roi_config,
)
from ..tracking.yolo_tracker import YoloPersonTracker
from ..scene_description.service import SceneDescriptionService
from ..visualization.overlay_renderer import (
    OverlayEventMarker,
    annotate_frame,
    marker_from_event,
    write_event_snapshot,
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
class LiveCameraState:
    camera_config: CameraConfig
    stream_status: str = "starting"
    last_frame_at: Optional[float] = None
    frame_index: int = -1
    timestamp_ms: int = 0
    track_count: int = 0
    pose_track_count: int = 0
    latest_event_count: int = 0
    latest_event_type: Optional[str] = None
    latest_event_id: Optional[str] = None
    latest_confidence: Optional[float] = None
    last_error: Optional[str] = None
    last_jpeg: Optional[bytes] = None
    total_events: int = 0
    unreviewed_events: int = 0
    fall_event_count: int = 0
    wandering_event_count: int = 0
    preview_mode: str = "live"
    width: int = 0
    height: int = 0
    event_markers: List[OverlayEventMarker] = field(default_factory=list)


class LiveMonitorService:
    def __init__(
        self,
        camera_configs: Sequence[Path],
        model_name: str = "yolo11n.pt",
        tracker_name: str = "bytetrack.yaml",
        confidence_threshold: float = 0.25,
        enable_pose: bool = True,
        enable_fall: bool = True,
        enable_wandering: bool = False,
        pose_model_path: Path = DATA_ROOT / "models" / "pose_landmarker_full.task",
        pose_min_detection_confidence: float = 0.5,
        pose_min_tracking_confidence: float = 0.5,
        fall_threshold_path: Path = CONFIG_ROOT / "thresholds" / "fall.yaml",
        roi_config_path: Optional[Path] = None,
        wandering_threshold_path: Path = CONFIG_ROOT / "thresholds" / "wandering.yaml",
        event_output_root: Path = ARTIFACT_ROOT / "events",
        clip_root: Path = ARTIFACT_ROOT / "clips",
        snapshot_root: Path = ARTIFACT_ROOT / "snapshots",
        scene_description_service: Optional[SceneDescriptionService] = None,
    ) -> None:
        self.camera_configs = [load_camera_config(path) for path in camera_configs]
        self.model_name = model_name
        self.tracker_name = tracker_name
        self.confidence_threshold = confidence_threshold
        self.enable_pose = enable_pose
        self.enable_fall = enable_fall
        self.enable_wandering = enable_wandering
        self.pose_model_path = pose_model_path
        self.pose_min_detection_confidence = pose_min_detection_confidence
        self.pose_min_tracking_confidence = pose_min_tracking_confidence
        self.fall_threshold_path = fall_threshold_path
        self.roi_config_path = roi_config_path
        self.wandering_threshold_path = wandering_threshold_path
        self.event_output_root = event_output_root
        self.clip_root = clip_root
        self.snapshot_root = snapshot_root
        self.scene_description_service = scene_description_service

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._states: Dict[str, LiveCameraState] = {
            config.camera_id: LiveCameraState(camera_config=config)
            for config in self.camera_configs
        }

    def start(self) -> None:
        for config in self.camera_configs:
            thread = threading.Thread(
                target=self._run_camera,
                args=(config,),
                name=f"live-monitor-{config.camera_id}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)

    def has_camera(self, camera_id: str) -> bool:
        with self._lock:
            return camera_id in self._states

    def get_camera_summaries(self) -> List[Dict[str, object]]:
        with self._lock:
            states = list(self._states.values())

        summaries: List[Dict[str, object]] = []
        for state in states:
            summaries.append(
                {
                    "camera_id": state.camera_config.camera_id,
                    "name": state.camera_config.name,
                    "location": state.camera_config.name,
                    "zone_label": state.camera_config.name,
                    "stream_status": state.stream_status,
                    "status_source": "live_monitor",
                    "source_type": state.camera_config.source_type,
                    "live_supported": True,
                    "live_frame_url": f"/api/live/cameras/{state.camera_config.camera_id}/frame",
                    "live_stream_url": f"/api/live/cameras/{state.camera_config.camera_id}/stream",
                    "last_seen_at": (
                        _isoformat_monotonic(state.last_frame_at)
                        if state.last_frame_at is not None
                        else None
                    ),
                    "total_events": state.total_events,
                    "unreviewed_events": state.unreviewed_events,
                    "fall_events": state.fall_event_count,
                    "wandering_events": state.wandering_event_count,
                    "latest_event_id": state.latest_event_id,
                    "latest_event_type": state.latest_event_type,
                    "latest_event_status": "new" if state.latest_event_id else "new",
                    "latest_event_started_at": (
                        _isoformat_monotonic(state.last_frame_at)
                        if state.last_frame_at is not None
                        else None
                    ),
                    "latest_confidence": state.latest_confidence,
                    "preview_snapshot_url": f"/api/live/cameras/{state.camera_config.camera_id}/frame",
                    "preview_clip_url": f"/api/live/cameras/{state.camera_config.camera_id}/stream",
                    "detail_event_url": (
                        f"/api/events/{state.latest_event_id}" if state.latest_event_id else None
                    ),
                    "input_fps": state.camera_config.target_fps,
                    "inference_fps": state.camera_config.target_fps,
                    "processing_delay_ms": None,
                    "current_track_count": state.track_count,
                    "current_pose_track_count": state.pose_track_count,
                    "last_error": state.last_error,
                }
            )

        return summaries

    def get_summary_fragment(self) -> Dict[str, object]:
        camera_summaries = self.get_camera_summaries()
        online_count = sum(
            1 for summary in camera_summaries if summary["stream_status"] == "online"
        )
        attention_count = sum(
            1 for summary in camera_summaries if summary["unreviewed_events"] > 0
        )
        return {
            "camera_total": len(camera_summaries),
            "camera_online": online_count,
            "camera_attention": attention_count,
        }

    def get_latest_frame(self, camera_id: str) -> Optional[bytes]:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return None
            return state.last_jpeg

    def get_state(self, camera_id: str) -> Optional[Dict[str, object]]:
        with self._lock:
            state = self._states.get(camera_id)
            if state is None:
                return None
            return {
                "camera_id": state.camera_config.camera_id,
                "name": state.camera_config.name,
                "stream_status": state.stream_status,
                "frame_index": state.frame_index,
                "timestamp_ms": state.timestamp_ms,
                "track_count": state.track_count,
                "pose_track_count": state.pose_track_count,
                "fall_event_count": state.fall_event_count,
                "wandering_event_count": state.wandering_event_count,
                "latest_event_count": state.latest_event_count,
                "latest_event_id": state.latest_event_id,
                "latest_event_type": state.latest_event_type,
                "latest_confidence": state.latest_confidence,
                "last_error": state.last_error,
                "width": state.width,
                "height": state.height,
            }

    def _run_camera(self, camera_config: CameraConfig) -> None:
        cv2 = _load_cv2()
        tracker = YoloPersonTracker(
            model_name=self.model_name,
            tracker_name=self.tracker_name,
            confidence_threshold=self.confidence_threshold,
        )
        pose_extractor = None
        if self.enable_pose:
            pose_extractor = MediaPipePoseExtractor(
                model_path=self.pose_model_path,
                min_detection_confidence=self.pose_min_detection_confidence,
                min_tracking_confidence=self.pose_min_tracking_confidence,
            )
        fall_engine = None
        if self.enable_fall:
            fall_engine = FallEventEngine.from_yaml(
                self.fall_threshold_path,
                profile=camera_config.fall_threshold_profile or camera_config.camera_id,
            )
        wandering_engine = None
        if self.enable_wandering:
            wandering_profile = (
                camera_config.wandering_threshold_profile or camera_config.camera_id
            )
            if self.roi_config_path is not None:
                wandering_engine = WanderingEventEngine.from_yaml(
                    roi_path=self.roi_config_path,
                    threshold_path=self.wandering_threshold_path,
                    profile=wandering_profile,
                )
            else:
                wandering_engine = WanderingEventEngine(
                    roi_config=build_full_frame_roi_config(
                        camera_id=camera_config.camera_id,
                        frame_width=camera_config.frame_width,
                        frame_height=camera_config.frame_height,
                    ),
                    thresholds=WanderingThresholds.from_yaml(
                        self.wandering_threshold_path,
                        profile=wandering_profile,
                    ),
                )

        frame_source = VideoFrameSource(camera_config)
        clip_manager = EventClipManager(
            clip_root=self.clip_root,
            snapshot_root=self.snapshot_root,
            target_fps=camera_config.target_fps,
        )
        event_file_path = self.event_output_root / f"live_{camera_config.camera_id}.jsonl"
        event_file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            while not self._stop_event.is_set():
                try:
                    for packet in frame_source.iter_frames():
                        if self._stop_event.is_set():
                            break
                        clip_manager.on_frame(packet)
                        observations = tracker.track_frame(
                            frame=packet.frame,
                            frame_index=packet.frame_index,
                            timestamp_ms=packet.timestamp_ms,
                        )
                        pose_by_track: Dict[int, PoseObservation] = {}
                        live_markers: List[OverlayEventMarker] = []
                        emitted_events: List[EventRecord] = []

                        for observation in observations:
                            if pose_extractor:
                                pose_observation = pose_extractor.extract_from_track(
                                    frame=packet.frame,
                                    observation=observation,
                                )
                                if pose_observation is not None:
                                    pose_by_track[observation.track_id] = pose_observation

                                    if fall_engine:
                                        events = fall_engine.update(
                                            camera_id=camera_config.camera_id,
                                            observation=observation,
                                            pose_observation=pose_observation,
                                        )
                                        for event in events:
                                            event = clip_manager.register_event(event)
                                            emitted_events.append(event)

                            if wandering_engine:
                                wandering_events = wandering_engine.update(
                                    camera_id=camera_config.camera_id,
                                    observation=observation,
                                )
                                for event in wandering_events:
                                    event = clip_manager.register_event(event)
                                    emitted_events.append(event)

                        for event in emitted_events:
                            if event.snapshot_path:
                                write_event_snapshot(
                                    cv2,
                                    Path(event.snapshot_path),
                                    packet.frame,
                                    observations=observations,
                                    pose_by_track=pose_by_track,
                                    event_marker=marker_from_event(event),
                                )
                            persist_event_record(
                                event_file_path,
                                event,
                                scene_description_service=self.scene_description_service,
                            )
                            live_markers.append(
                                marker_from_event(event)
                            )

                        overlay_frame = annotate_frame(
                            cv2,
                            packet.frame,
                            observations=observations,
                            pose_by_track=pose_by_track,
                            event_markers=live_markers,
                            camera_id=camera_config.camera_id,
                            frame_index=packet.frame_index,
                            timestamp_ms=packet.timestamp_ms,
                            include_header=True,
                        )

                        encoded_ok, encoded = cv2.imencode(
                            ".jpg",
                            overlay_frame,
                            [int(cv2.IMWRITE_JPEG_QUALITY), 82],
                        )
                        if not encoded_ok:
                            continue

                        fall_events_delta = sum(
                            1
                            for event in emitted_events
                            if event.event_type.value == "fall_suspected"
                        )
                        wandering_events_delta = sum(
                            1
                            for event in emitted_events
                            if event.event_type.value == "wandering_suspected"
                        )
                        self._update_state(
                            camera_id=camera_config.camera_id,
                            stream_status="online",
                            last_frame_at=time.time(),
                            frame_index=packet.frame_index,
                            timestamp_ms=packet.timestamp_ms,
                            track_count=len(observations),
                            pose_track_count=len(pose_by_track),
                            latest_event_count=len(emitted_events),
                            latest_event_id=emitted_events[-1].event_id if emitted_events else None,
                            latest_event_type=(
                                emitted_events[-1].event_type.value if emitted_events else None
                            ),
                            latest_confidence=(
                                emitted_events[-1].confidence if emitted_events else None
                            ),
                            last_error=None,
                            last_jpeg=encoded.tobytes(),
                            width=overlay_frame.shape[1],
                            height=overlay_frame.shape[0],
                            total_events_delta=len(emitted_events),
                            fall_events_delta=fall_events_delta,
                            wandering_events_delta=wandering_events_delta,
                        )
                except Exception as exc:  # pragma: no cover - runtime dependent
                    self._update_state(
                        camera_id=camera_config.camera_id,
                        stream_status="offline",
                        last_error=str(exc),
                    )
                    time.sleep(1.5)
        finally:
            clip_manager.close()
            if pose_extractor is not None:
                pose_extractor.close()

    def _update_state(
        self,
        camera_id: str,
        stream_status: Optional[str] = None,
        last_frame_at: Optional[float] = None,
        frame_index: Optional[int] = None,
        timestamp_ms: Optional[int] = None,
        track_count: Optional[int] = None,
        pose_track_count: Optional[int] = None,
        latest_event_count: Optional[int] = None,
        latest_event_id: Optional[str] = None,
        latest_event_type: Optional[str] = None,
        latest_confidence: Optional[float] = None,
        last_error: Optional[str] = None,
        last_jpeg: Optional[bytes] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        total_events_delta: int = 0,
        fall_events_delta: int = 0,
        wandering_events_delta: int = 0,
    ) -> None:
        with self._lock:
            state = self._states[camera_id]
            if stream_status is not None:
                state.stream_status = stream_status
            if last_frame_at is not None:
                state.last_frame_at = last_frame_at
            if frame_index is not None:
                state.frame_index = frame_index
            if timestamp_ms is not None:
                state.timestamp_ms = timestamp_ms
            if track_count is not None:
                state.track_count = track_count
            if pose_track_count is not None:
                state.pose_track_count = pose_track_count
            if latest_event_count is not None:
                state.latest_event_count = latest_event_count
            if latest_event_id is not None:
                state.latest_event_id = latest_event_id
            if latest_event_type is not None:
                state.latest_event_type = latest_event_type
            if latest_confidence is not None:
                state.latest_confidence = latest_confidence
            if last_error is not None or stream_status == "offline":
                state.last_error = last_error
            if last_jpeg is not None:
                state.last_jpeg = last_jpeg
            if width is not None:
                state.width = width
            if height is not None:
                state.height = height
            if total_events_delta:
                state.total_events += total_events_delta
                state.unreviewed_events += total_events_delta
            if fall_events_delta:
                state.fall_event_count += fall_events_delta
            if wandering_events_delta:
                state.wandering_event_count += wandering_events_delta


def _isoformat_monotonic(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(value))
