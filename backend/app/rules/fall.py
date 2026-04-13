from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

from ..config import load_yaml_file
from ..events.schema import EventRecord, EventType
from ..pose.types import PoseLandmarkRecord, PoseObservation
from ..tracking.types import TrackObservation


LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24


@dataclass
class FallThresholds:
    center_drop_pixels: float
    angle_change_degrees: float
    horizontal_ratio_threshold: float
    no_motion_seconds: float
    cooldown_seconds: float
    max_motion_pixels: float = 12.0
    fall_window_seconds: float = 1.0
    min_pose_confidence: float = 0.3
    horizontal_angle_threshold: float = 60.0
    upright_angle_threshold: float = 25.0
    center_drop_height_ratio: float = 0.0
    horizontal_persistence_seconds: float = 0.0
    max_confirmation_seconds: float = 0.0
    min_forward_drop_pixels: float = 0.0
    min_forward_drop_ratio: float = 0.0
    min_confirmation_angle_change_degrees: float = 0.0
    min_episode_peak_angle_degrees: float = 0.0

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        profile: Optional[str] = None,
    ) -> "FallThresholds":
        payload = cls._load_threshold_payload(path, profile)
        return cls(
            center_drop_pixels=float(payload["center_drop_pixels"]),
            angle_change_degrees=float(payload["angle_change_degrees"]),
            horizontal_ratio_threshold=float(payload["horizontal_ratio_threshold"]),
            no_motion_seconds=float(payload["no_motion_seconds"]),
            cooldown_seconds=float(payload["cooldown_seconds"]),
            max_motion_pixels=float(payload.get("max_motion_pixels", 12.0)),
            fall_window_seconds=float(payload.get("fall_window_seconds", 1.0)),
            min_pose_confidence=float(payload.get("min_pose_confidence", 0.3)),
            horizontal_angle_threshold=float(
                payload.get("horizontal_angle_threshold", 60.0)
            ),
            upright_angle_threshold=float(payload.get("upright_angle_threshold", 25.0)),
            center_drop_height_ratio=float(payload.get("center_drop_height_ratio", 0.0)),
            horizontal_persistence_seconds=float(
                payload.get("horizontal_persistence_seconds", 0.0)
            ),
            max_confirmation_seconds=float(
                payload.get("max_confirmation_seconds", 0.0)
            ),
            min_forward_drop_pixels=float(payload.get("min_forward_drop_pixels", 0.0)),
            min_forward_drop_ratio=float(payload.get("min_forward_drop_ratio", 0.0)),
            min_confirmation_angle_change_degrees=float(
                payload.get("min_confirmation_angle_change_degrees", 0.0)
            ),
            min_episode_peak_angle_degrees=float(
                payload.get("min_episode_peak_angle_degrees", 0.0)
            ),
        )

    @staticmethod
    def _load_threshold_payload(
        path: Path,
        profile: Optional[str],
    ) -> Dict[str, Any]:
        payload = dict(load_yaml_file(path))
        profiles = payload.pop("profiles", {})
        if profile is None:
            return payload
        if not profiles:
            return payload
        if not isinstance(profiles, dict):
            raise ValueError("profiles must be a mapping when present in threshold YAML")
        override = profiles.get(profile)
        if override is None:
            return payload
        if not isinstance(override, dict):
            raise ValueError(f"profile override for {profile!r} must be a mapping")
        merged = dict(payload)
        merged.update(override)
        return merged


@dataclass
class FallMetricSample:
    timestamp_ms: int
    center_y: float
    torso_angle: float
    aspect_ratio: float
    bbox_height: float


@dataclass
class FallTrackState:
    phase: str = "NORMAL"
    history: Deque[FallMetricSample] = field(default_factory=deque)
    last_pose: Optional[PoseObservation] = None
    collapse_started_at_ms: Optional[int] = None
    suspected_at_ms: Optional[int] = None
    last_event_timestamp_ms: Optional[int] = None
    horizontal_started_at_ms: Optional[int] = None
    peak_torso_angle: Optional[float] = None


class FallEventEngine:
    def __init__(self, thresholds: FallThresholds):
        self.thresholds = thresholds
        self.track_states: Dict[int, FallTrackState] = {}

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        profile: Optional[str] = None,
    ) -> "FallEventEngine":
        return cls(FallThresholds.from_yaml(path, profile=profile))

    def update(
        self,
        camera_id: str,
        observation: TrackObservation,
        pose_observation: PoseObservation,
    ) -> List[EventRecord]:
        if pose_observation.confidence < self.thresholds.min_pose_confidence:
            return []

        torso_angle = self._compute_torso_angle_degrees(pose_observation.landmarks)
        if torso_angle is None:
            return []

        center_y = (observation.y1 + observation.y2) / 2.0
        width = max(1.0, observation.x2 - observation.x1)
        height = max(1.0, observation.y2 - observation.y1)
        aspect_ratio = width / height

        state = self.track_states.setdefault(observation.track_id, FallTrackState())
        self._prune_history(state.history, observation.timestamp_ms)
        state.history.append(
            FallMetricSample(
                timestamp_ms=observation.timestamp_ms,
                center_y=center_y,
                torso_angle=torso_angle,
                aspect_ratio=aspect_ratio,
                bbox_height=height,
            )
        )

        motion_pixels = self._compute_motion_pixels(state.last_pose, pose_observation)
        state.last_pose = pose_observation

        reference_sample = state.history[0]
        center_drop = center_y - reference_sample.center_y
        center_drop_ratio = center_drop / max(reference_sample.bbox_height, 1.0)
        angle_change = abs(torso_angle - reference_sample.torso_angle)

        horizontal_ratio_pose = aspect_ratio >= self.thresholds.horizontal_ratio_threshold
        horizontal_angle_pose = torso_angle >= self.thresholds.horizontal_angle_threshold
        horizontal_pose = horizontal_ratio_pose or horizontal_angle_pose
        rapid_drop = self._meets_drop_threshold(
            center_drop=center_drop,
            center_drop_ratio=center_drop_ratio,
        )
        normalized_drop = self._meets_normalized_drop_threshold(center_drop_ratio)
        forward_drop = self._has_forward_drop_evidence(
            center_drop=center_drop,
            center_drop_ratio=center_drop_ratio,
        )
        rapid_angle = angle_change >= self.thresholds.angle_change_degrees
        low_motion = (
            motion_pixels is not None
            and motion_pixels <= self.thresholds.max_motion_pixels
        )
        upright_pose = (
            aspect_ratio < self.thresholds.horizontal_ratio_threshold
            and torso_angle <= self.thresholds.upright_angle_threshold
        )

        if self._is_in_cooldown(state, observation.timestamp_ms):
            if upright_pose:
                self._reset_collapse_markers(state)
            return []

        if self._has_confirmation_timed_out(state, observation.timestamp_ms):
            state.phase = "NORMAL"
            self._reset_collapse_markers(state)
            return []

        if state.phase == "FALL_CONFIRMED":
            if upright_pose:
                state.phase = "RECOVERED"
                self._reset_collapse_markers(state)
            return []

        suspected_trigger = (rapid_drop and (rapid_angle or horizontal_pose)) or (
            horizontal_ratio_pose and rapid_angle
        )
        if suspected_trigger:
            if state.phase == "NORMAL":
                state.phase = "FALL_SUSPECTED"
                state.suspected_at_ms = observation.timestamp_ms
                state.peak_torso_angle = torso_angle
                if horizontal_pose:
                    state.horizontal_started_at_ms = observation.timestamp_ms

        if state.phase in {"FALL_SUSPECTED", "LYING_OR_COLLAPSED", "FALL_CONFIRMED"}:
            if state.peak_torso_angle is None:
                state.peak_torso_angle = torso_angle
            else:
                state.peak_torso_angle = max(state.peak_torso_angle, torso_angle)

        if state.phase == "FALL_SUSPECTED":
            if horizontal_pose:
                if state.horizontal_started_at_ms is None:
                    state.horizontal_started_at_ms = observation.timestamp_ms
                persistence_elapsed_ms = (
                    observation.timestamp_ms - state.horizontal_started_at_ms
                )
                if persistence_elapsed_ms >= int(
                    self.thresholds.horizontal_persistence_seconds * 1000
                ):
                    collapse_pose = normalized_drop or rapid_drop or (
                        horizontal_ratio_pose and horizontal_angle_pose and forward_drop
                    )
                    if collapse_pose:
                        state.phase = "LYING_OR_COLLAPSED"
                        if state.collapse_started_at_ms is None:
                            state.collapse_started_at_ms = observation.timestamp_ms
            elif upright_pose:
                state.phase = "NORMAL"
                self._reset_collapse_markers(state)
            else:
                state.horizontal_started_at_ms = None

        if state.phase == "LYING_OR_COLLAPSED":
            if not horizontal_pose:
                state.phase = "NORMAL"
                self._reset_collapse_markers(state)
                return []

            if low_motion:
                if state.collapse_started_at_ms is None:
                    state.collapse_started_at_ms = observation.timestamp_ms
                elapsed_ms = observation.timestamp_ms - state.collapse_started_at_ms
                confirmation_angle_change_ok = (
                    self.thresholds.min_confirmation_angle_change_degrees <= 0
                    or angle_change
                    >= self.thresholds.min_confirmation_angle_change_degrees
                    or normalized_drop
                    or rapid_drop
                )
                confirmation_peak_angle_ok = (
                    self.thresholds.min_episode_peak_angle_degrees <= 0
                    or (
                        state.peak_torso_angle is not None
                        and state.peak_torso_angle
                        >= self.thresholds.min_episode_peak_angle_degrees
                    )
                    or torso_angle <= self.thresholds.upright_angle_threshold
                )
                if (
                    elapsed_ms >= int(self.thresholds.no_motion_seconds * 1000)
                    and confirmation_angle_change_ok
                    and confirmation_peak_angle_ok
                ):
                    state.phase = "FALL_CONFIRMED"
                    state.last_event_timestamp_ms = observation.timestamp_ms
                    return [
                        self._build_event(
                            camera_id=camera_id,
                            observation=observation,
                            pose_observation=pose_observation,
                            center_drop=center_drop,
                            center_drop_ratio=center_drop_ratio,
                            angle_change=angle_change,
                            aspect_ratio=aspect_ratio,
                            motion_pixels=motion_pixels or 0.0,
                        )
                    ]
            else:
                state.collapse_started_at_ms = observation.timestamp_ms

        return []

    def _is_in_cooldown(self, state: FallTrackState, timestamp_ms: int) -> bool:
        if state.last_event_timestamp_ms is None:
            return False
        cooldown_ms = int(self.thresholds.cooldown_seconds * 1000)
        return (timestamp_ms - state.last_event_timestamp_ms) < cooldown_ms

    def _has_confirmation_timed_out(
        self,
        state: FallTrackState,
        timestamp_ms: int,
    ) -> bool:
        if self.thresholds.max_confirmation_seconds <= 0:
            return False
        if state.suspected_at_ms is None:
            return False
        confirmation_window_ms = int(self.thresholds.max_confirmation_seconds * 1000)
        return (timestamp_ms - state.suspected_at_ms) > confirmation_window_ms

    def _reset_collapse_markers(self, state: FallTrackState) -> None:
        state.collapse_started_at_ms = None
        state.suspected_at_ms = None
        state.horizontal_started_at_ms = None
        state.peak_torso_angle = None

    def _meets_drop_threshold(
        self,
        *,
        center_drop: float,
        center_drop_ratio: float,
    ) -> bool:
        meets_pixel_threshold = center_drop >= self.thresholds.center_drop_pixels
        if self.thresholds.center_drop_height_ratio > 0:
            return (
                meets_pixel_threshold
                or center_drop_ratio >= self.thresholds.center_drop_height_ratio
            )
        return meets_pixel_threshold

    def _meets_normalized_drop_threshold(self, center_drop_ratio: float) -> bool:
        if self.thresholds.center_drop_height_ratio <= 0:
            return False
        return center_drop_ratio >= self.thresholds.center_drop_height_ratio

    def _has_forward_drop_evidence(
        self,
        *,
        center_drop: float,
        center_drop_ratio: float,
    ) -> bool:
        pixel_threshold = self.thresholds.min_forward_drop_pixels
        ratio_threshold = self.thresholds.min_forward_drop_ratio
        if pixel_threshold <= 0 and ratio_threshold <= 0:
            return center_drop > 0
        meets_pixel = pixel_threshold > 0 and center_drop >= pixel_threshold
        meets_ratio = ratio_threshold > 0 and center_drop_ratio >= ratio_threshold
        return meets_pixel or meets_ratio

    def _prune_history(
        self,
        history: Deque[FallMetricSample],
        timestamp_ms: int,
    ) -> None:
        window_ms = int(self.thresholds.fall_window_seconds * 1000)
        while history and (timestamp_ms - history[0].timestamp_ms) > window_ms:
            history.popleft()

    def _compute_torso_angle_degrees(
        self,
        landmarks: List[PoseLandmarkRecord],
    ) -> Optional[float]:
        landmark_map = {landmark.index: landmark for landmark in landmarks}
        needed_indices = [LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_HIP, RIGHT_HIP]
        if any(index not in landmark_map for index in needed_indices):
            return None

        shoulder_center = self._average_point(
            landmark_map[LEFT_SHOULDER], landmark_map[RIGHT_SHOULDER]
        )
        hip_center = self._average_point(landmark_map[LEFT_HIP], landmark_map[RIGHT_HIP])
        delta_x = abs(shoulder_center[0] - hip_center[0])
        delta_y = abs(shoulder_center[1] - hip_center[1])
        if delta_x == 0 and delta_y == 0:
            return None

        # Angle from vertical: 0 means upright, 90 means horizontal.
        import math

        return math.degrees(math.atan2(delta_x, max(delta_y, 1e-6)))

    def _average_point(
        self,
        a: PoseLandmarkRecord,
        b: PoseLandmarkRecord,
    ) -> Tuple[float, float]:
        return ((a.x + b.x) / 2.0, (a.y + b.y) / 2.0)

    def _compute_motion_pixels(
        self,
        previous_pose: Optional[PoseObservation],
        current_pose: PoseObservation,
    ) -> Optional[float]:
        if previous_pose is None:
            return None

        previous_map = {landmark.index: landmark for landmark in previous_pose.landmarks}
        motions = []
        for landmark in current_pose.landmarks:
            previous_landmark = previous_map.get(landmark.index)
            if previous_landmark is None:
                continue
            dx = landmark.x - previous_landmark.x
            dy = landmark.y - previous_landmark.y
            motions.append((dx * dx + dy * dy) ** 0.5)

        if not motions:
            return None
        return sum(motions) / len(motions)

    def _build_event(
        self,
        camera_id: str,
        observation: TrackObservation,
        pose_observation: PoseObservation,
        center_drop: float,
        center_drop_ratio: float,
        angle_change: float,
        aspect_ratio: float,
        motion_pixels: float,
    ) -> EventRecord:
        confidence = self._compute_confidence(
            center_drop=center_drop,
            center_drop_ratio=center_drop_ratio,
            angle_change=angle_change,
            aspect_ratio=aspect_ratio,
            motion_pixels=motion_pixels,
            pose_confidence=pose_observation.confidence,
        )
        timestamp = datetime.now().astimezone()
        event_id = "fall_{camera}_{track}_{ts}".format(
            camera=camera_id,
            track=observation.track_id,
            ts=observation.timestamp_ms,
        )
        return EventRecord(
            event_id=event_id,
            camera_id=camera_id,
            track_id=observation.track_id,
            event_type=EventType.FALL_SUSPECTED,
            started_at=timestamp,
            ended_at=timestamp,
            source_timestamp_ms=observation.timestamp_ms,
            confidence=confidence,
            description="실신 의심: 급격한 자세 붕괴 후 움직임이 거의 없음",
            details={
                "phase": "FALL_CONFIRMED",
                "target_bbox": [
                    round(observation.x1, 3),
                    round(observation.y1, 3),
                    round(observation.x2, 3),
                    round(observation.y2, 3),
                ],
                "center_drop_pixels": round(center_drop, 3),
                "center_drop_ratio": round(center_drop_ratio, 3),
                "angle_change_degrees": round(angle_change, 3),
                "aspect_ratio": round(aspect_ratio, 3),
                "motion_pixels": round(motion_pixels, 3),
                "pose_confidence": round(pose_observation.confidence, 3),
            },
        )

    def _compute_confidence(
        self,
        center_drop: float,
        center_drop_ratio: float,
        angle_change: float,
        aspect_ratio: float,
        motion_pixels: float,
        pose_confidence: float,
    ) -> float:
        drop_scores = []
        if self.thresholds.center_drop_pixels > 0:
            drop_scores.append(
                min(1.0, max(0.0, center_drop / self.thresholds.center_drop_pixels))
            )
        if self.thresholds.center_drop_height_ratio > 0:
            drop_scores.append(
                min(
                    1.0,
                    max(
                        0.0,
                        center_drop_ratio / self.thresholds.center_drop_height_ratio,
                    ),
                )
            )
        drop_score = max(drop_scores) if drop_scores else 0.0
        angle_score = min(
            1.0, max(0.0, angle_change / self.thresholds.angle_change_degrees)
        )
        ratio_score = min(
            1.0,
            max(0.0, aspect_ratio / self.thresholds.horizontal_ratio_threshold),
        )
        motion_score = 1.0 - min(
            1.0,
            max(0.0, motion_pixels / self.thresholds.max_motion_pixels),
        )
        confidence = (
            drop_score + angle_score + ratio_score + motion_score + pose_confidence
        ) / 5.0
        return round(confidence, 3)
