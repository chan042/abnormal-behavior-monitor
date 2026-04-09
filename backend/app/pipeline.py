from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, Optional

from .config import CameraConfig, load_camera_config
from .events.clip_manager import EventClipManager
from .events.schema import EventRecord
from .ingestion.frame_source import VideoFrameSource
from .paths import ARTIFACT_ROOT
from .pose.mediapipe_pose import MediaPipePoseExtractor
from .rules.fall import FallEventEngine
from .rules.wandering import WanderingEventEngine
from .tracking.yolo_tracker import YoloPersonTracker


def run_tracking_pipeline(
    camera_config_path: Path,
    output_path: Path,
    max_frames: Optional[int] = None,
    model_name: str = "yolo11n.pt",
    tracker_name: str = "bytetrack.yaml",
    confidence_threshold: float = 0.25,
    enable_pose: bool = False,
    enable_fall: bool = False,
    enable_wandering: bool = False,
    pose_output_path: Optional[Path] = None,
    pose_model_path: Optional[Path] = None,
    pose_model_complexity: int = 1,
    pose_min_detection_confidence: float = 0.5,
    pose_min_tracking_confidence: float = 0.5,
    fall_threshold_path: Optional[Path] = None,
    roi_config_path: Optional[Path] = None,
    wandering_threshold_path: Optional[Path] = None,
    event_output_path: Optional[Path] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    clip_root: Optional[Path] = None,
    snapshot_root: Optional[Path] = None,
) -> Dict[str, object]:
    camera_config = load_camera_config(camera_config_path)
    return run_tracking_pipeline_for_camera(
        camera_config=camera_config,
        output_path=output_path,
        max_frames=max_frames,
        model_name=model_name,
        tracker_name=tracker_name,
        confidence_threshold=confidence_threshold,
        enable_pose=enable_pose,
        enable_fall=enable_fall,
        enable_wandering=enable_wandering,
        pose_output_path=pose_output_path,
        pose_model_path=pose_model_path,
        pose_model_complexity=pose_model_complexity,
        pose_min_detection_confidence=pose_min_detection_confidence,
        pose_min_tracking_confidence=pose_min_tracking_confidence,
        fall_threshold_path=fall_threshold_path,
        roi_config_path=roi_config_path,
        wandering_threshold_path=wandering_threshold_path,
        event_output_path=event_output_path,
        start_ms=start_ms,
        end_ms=end_ms,
        clip_root=clip_root,
        snapshot_root=snapshot_root,
    )


def run_tracking_pipeline_for_camera(
    camera_config: CameraConfig,
    output_path: Path,
    max_frames: Optional[int] = None,
    model_name: str = "yolo11n.pt",
    tracker_name: str = "bytetrack.yaml",
    confidence_threshold: float = 0.25,
    enable_pose: bool = False,
    enable_fall: bool = False,
    enable_wandering: bool = False,
    pose_output_path: Optional[Path] = None,
    pose_model_path: Optional[Path] = None,
    pose_model_complexity: int = 1,
    pose_min_detection_confidence: float = 0.5,
    pose_min_tracking_confidence: float = 0.5,
    fall_threshold_path: Optional[Path] = None,
    roi_config_path: Optional[Path] = None,
    wandering_threshold_path: Optional[Path] = None,
    event_output_path: Optional[Path] = None,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    clip_root: Optional[Path] = None,
    snapshot_root: Optional[Path] = None,
) -> Dict[str, object]:
    frame_source = VideoFrameSource(camera_config)
    tracker = YoloPersonTracker(
        model_name=model_name,
        tracker_name=tracker_name,
        confidence_threshold=confidence_threshold,
    )
    pose_extractor = None
    if enable_pose:
        pose_extractor = MediaPipePoseExtractor(
            model_path=pose_model_path,
            model_complexity=pose_model_complexity,
            min_detection_confidence=pose_min_detection_confidence,
            min_tracking_confidence=pose_min_tracking_confidence,
        )
    fall_engine = None
    if enable_fall:
        if fall_threshold_path is None:
            raise ValueError("fall_threshold_path is required when fall detection is enabled")
        fall_profile = camera_config.fall_threshold_profile or camera_config.camera_id
        fall_engine = FallEventEngine.from_yaml(
            fall_threshold_path,
            profile=fall_profile,
        )
    wandering_engine = None
    if enable_wandering:
        if roi_config_path is None:
            raise ValueError("roi_config_path is required when wandering detection is enabled")
        if wandering_threshold_path is None:
            raise ValueError(
                "wandering_threshold_path is required when wandering detection is enabled"
            )
        wandering_engine = WanderingEventEngine.from_yaml(
            roi_path=roi_config_path,
            threshold_path=wandering_threshold_path,
        )
    clip_manager = None
    if enable_fall or enable_wandering:
        clip_manager = EventClipManager(
            clip_root=clip_root or (ARTIFACT_ROOT / "clips"),
            snapshot_root=snapshot_root or (ARTIFACT_ROOT / "snapshots"),
            target_fps=camera_config.target_fps,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if pose_output_path:
        pose_output_path.parent.mkdir(parents=True, exist_ok=True)
    if event_output_path:
        event_output_path.parent.mkdir(parents=True, exist_ok=True)

    frame_count = 0
    observation_count = 0
    pose_observation_count = 0
    event_count = 0
    wandering_event_count = 0
    fall_event_count = 0
    unique_track_ids = set()
    class_counter = Counter()

    pose_file = None
    if enable_pose and pose_output_path is not None:
        pose_file = pose_output_path.open("w", encoding="utf-8")
    event_file = None
    if (enable_fall or enable_wandering) and event_output_path is not None:
        event_file = event_output_path.open("w", encoding="utf-8")

    try:
        with output_path.open("w", encoding="utf-8") as output_file:
            for packet in frame_source.iter_frames(
                max_frames=max_frames,
                start_ms=start_ms,
                end_ms=end_ms,
            ):
                frame_count += 1
                if clip_manager:
                    clip_manager.on_frame(packet)
                observations = tracker.track_frame(
                    frame=packet.frame,
                    frame_index=packet.frame_index,
                    timestamp_ms=packet.timestamp_ms,
                )
                for observation in observations:
                    payload = observation.to_dict()
                    payload["camera_id"] = camera_config.camera_id
                    output_file.write(json.dumps(payload, ensure_ascii=True) + "\n")
                    observation_count += 1
                    unique_track_ids.add(observation.track_id)
                    class_counter[observation.class_name] += 1

                    if wandering_engine and event_file:
                        wandering_events = wandering_engine.update(
                            camera_id=camera_config.camera_id,
                            observation=observation,
                        )
                        for event in wandering_events:
                            if clip_manager:
                                event = clip_manager.register_event(event)
                            _write_event(event_file, event)
                            event_count += 1
                            wandering_event_count += 1

                    if pose_extractor and pose_file:
                        pose_observation = pose_extractor.extract_from_track(
                            frame=packet.frame,
                            observation=observation,
                        )
                        if pose_observation is None:
                            continue
                        pose_payload = pose_observation.to_dict()
                        pose_payload["camera_id"] = camera_config.camera_id
                        pose_file.write(json.dumps(pose_payload, ensure_ascii=True) + "\n")
                        pose_observation_count += 1

                        if fall_engine and event_file:
                            events = fall_engine.update(
                                camera_id=camera_config.camera_id,
                                observation=observation,
                                pose_observation=pose_observation,
                            )
                            for event in events:
                                if clip_manager:
                                    event = clip_manager.register_event(event)
                                _write_event(event_file, event)
                                event_count += 1
                                fall_event_count += 1
    finally:
        if clip_manager:
            clip_manager.close()
        if pose_extractor:
            pose_extractor.close()
        if pose_file:
            pose_file.close()
        if event_file:
            event_file.close()

    return {
        "camera_id": camera_config.camera_id,
        "source": camera_config.source,
        "frames_processed": frame_count,
        "observations_written": observation_count,
        "pose_observations_written": pose_observation_count,
        "events_written": event_count,
        "fall_events_written": fall_event_count,
        "wandering_events_written": wandering_event_count,
        "unique_track_ids": len(unique_track_ids),
        "output_path": str(output_path),
        "pose_output_path": str(pose_output_path) if pose_output_path else None,
        "pose_model_path": str(pose_model_path) if pose_model_path else None,
        "event_output_path": str(event_output_path) if event_output_path else None,
        "roi_config_path": str(roi_config_path) if roi_config_path else None,
        "class_counts": dict(class_counter),
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def _write_event(event_file: object, event: EventRecord) -> None:
    event_file.write(json.dumps(event.to_dict(), ensure_ascii=True) + "\n")
