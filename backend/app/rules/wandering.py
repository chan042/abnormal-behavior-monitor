from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import hypot
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Sequence, Tuple

from ..config import Roi, RoiConfig, load_roi_config, load_yaml_file
from ..events.schema import EventRecord, EventType
from ..tracking.types import TrackObservation


PositionSample = Tuple[float, float, int]


def build_full_frame_roi_config(
    *,
    camera_id: str,
    frame_width: int,
    frame_height: int,
) -> RoiConfig:
    width = max(int(frame_width), 1)
    height = max(int(frame_height), 1)
    return RoiConfig(
        camera_id=camera_id,
        rois=[
            Roi(
                roi_id="full_frame",
                name="Full Frame",
                points=[[0, 0], [width, 0], [width, height], [0, height]],
                axis=None,
                event_types=["wandering"],
            )
        ],
    )


@dataclass
class WanderingThresholds:
    min_dwell_seconds: float
    min_round_trips: int
    min_direction_changes: int
    min_path_to_displacement_ratio: float
    cooldown_seconds: float
    min_step_pixels: float = 12.0
    window_seconds: float = 180.0
    max_track_gap_seconds: float = 2.0
    reentry_grace_seconds: float = 1.0
    min_total_distance_pixels: float = 240.0
    min_axis_excursion_pixels: float = 0.0
    max_idle_ratio: float = 0.75
    max_relink_distance_pixels: float = 220.0

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        profile: Optional[str] = None,
    ) -> "WanderingThresholds":
        payload = cls._load_threshold_payload(path, profile)
        return cls(
            min_dwell_seconds=float(payload["min_dwell_seconds"]),
            min_round_trips=int(payload["min_round_trips"]),
            min_direction_changes=int(payload["min_direction_changes"]),
            min_path_to_displacement_ratio=float(payload["min_path_to_displacement_ratio"]),
            cooldown_seconds=float(payload["cooldown_seconds"]),
            min_step_pixels=float(payload.get("min_step_pixels", 12.0)),
            window_seconds=float(payload.get("window_seconds", 180.0)),
            max_track_gap_seconds=float(payload.get("max_track_gap_seconds", 2.0)),
            reentry_grace_seconds=float(payload.get("reentry_grace_seconds", 1.0)),
            min_total_distance_pixels=float(
                payload.get("min_total_distance_pixels", 240.0)
            ),
            min_axis_excursion_pixels=float(
                payload.get("min_axis_excursion_pixels", 0.0)
            ),
            max_idle_ratio=float(payload.get("max_idle_ratio", 0.75)),
            max_relink_distance_pixels=float(
                payload.get("max_relink_distance_pixels", 220.0)
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
class WanderingTrackState:
    phase: str = "IDLE"
    active_roi_id: Optional[str] = None
    episode_started_at_ms: Optional[int] = None
    last_seen_at_ms: Optional[int] = None
    outside_since_ms: Optional[int] = None
    positions: Deque[PositionSample] = field(default_factory=deque)
    last_event_timestamp_ms: Optional[int] = None
    last_event_direction_changes: int = 0
    last_event_round_trips: int = 0

    def start_episode(self, roi_id: str, timestamp_ms: int) -> None:
        self.phase = "OBSERVING"
        self.active_roi_id = roi_id
        self.episode_started_at_ms = timestamp_ms
        self.last_seen_at_ms = timestamp_ms
        self.outside_since_ms = None
        self.positions = deque()
        self.last_event_timestamp_ms = None
        self.last_event_direction_changes = 0
        self.last_event_round_trips = 0

    def reset(self) -> None:
        self.phase = "IDLE"
        self.active_roi_id = None
        self.episode_started_at_ms = None
        self.last_seen_at_ms = None
        self.outside_since_ms = None
        self.positions = deque()
        self.last_event_timestamp_ms = None
        self.last_event_direction_changes = 0
        self.last_event_round_trips = 0


class WanderingEventEngine:
    def __init__(self, roi_config: RoiConfig, thresholds: WanderingThresholds):
        self.roi_config = roi_config
        self.thresholds = thresholds
        self.track_states: Dict[int, WanderingTrackState] = {}
        self.axis_by_roi_id = {
            roi.roi_id: roi.axis or self._dominant_axis(roi.points)
            for roi in roi_config.rois
        }

    @classmethod
    def from_yaml(
        cls,
        roi_path: Path,
        threshold_path: Path,
        profile: Optional[str] = None,
    ) -> "WanderingEventEngine":
        return cls(
            roi_config=load_roi_config(roi_path),
            thresholds=WanderingThresholds.from_yaml(threshold_path, profile=profile),
        )

    def update(
        self,
        camera_id: str,
        observation: TrackObservation,
    ) -> list[EventRecord]:
        center = self._motion_anchor(observation)
        roi = self._find_roi(center)
        state = self.track_states.setdefault(observation.track_id, WanderingTrackState())

        self._reset_for_track_gap(state, observation.timestamp_ms)

        if roi is None:
            self._handle_outside_roi(state, observation.timestamp_ms)
            return []

        relinked_state = self._relink_recent_episode(
            track_id=observation.track_id,
            roi_id=roi.roi_id,
            center=center,
            timestamp_ms=observation.timestamp_ms,
        )
        if relinked_state is not None:
            state = relinked_state

        if state.active_roi_id is None or state.active_roi_id != roi.roi_id:
            state.start_episode(roi.roi_id, observation.timestamp_ms)
        elif (
            state.outside_since_ms is not None
            and observation.timestamp_ms - state.outside_since_ms
            > int(self.thresholds.reentry_grace_seconds * 1000)
        ):
            state.start_episode(roi.roi_id, observation.timestamp_ms)

        state.last_seen_at_ms = observation.timestamp_ms
        state.outside_since_ms = None
        self._append_position(state, center, observation.timestamp_ms)

        metrics = self._compute_metrics(state, roi, observation.timestamp_ms)
        if self._should_emit_event(state, metrics, observation.timestamp_ms):
            state.phase = "WANDERING_SUSPECTED"
            state.last_event_timestamp_ms = observation.timestamp_ms
            state.last_event_direction_changes = int(metrics["direction_changes"])
            state.last_event_round_trips = int(metrics["round_trips"])
            return [
                self._build_event(
                    camera_id=camera_id,
                    observation=observation,
                    track_id=observation.track_id,
                    roi_id=roi.roi_id,
                    timestamp_ms=observation.timestamp_ms,
                    metrics=metrics,
                    axis=self.axis_by_roi_id.get(roi.roi_id, "x"),
                )
            ]

        if self._is_in_cooldown(state, observation.timestamp_ms):
            state.phase = "COOLDOWN"
        else:
            state.phase = "OBSERVING"
        return []

    def _reset_for_track_gap(
        self,
        state: WanderingTrackState,
        timestamp_ms: int,
    ) -> None:
        if state.last_seen_at_ms is None:
            return
        gap_ms = timestamp_ms - state.last_seen_at_ms
        if gap_ms > int(self.thresholds.max_track_gap_seconds * 1000):
            state.reset()

    def _handle_outside_roi(
        self,
        state: WanderingTrackState,
        timestamp_ms: int,
    ) -> None:
        state.last_seen_at_ms = timestamp_ms
        if state.active_roi_id is None:
            return
        if state.outside_since_ms is None:
            state.outside_since_ms = timestamp_ms
            return
        if (
            timestamp_ms - state.outside_since_ms
            > int(self.thresholds.reentry_grace_seconds * 1000)
        ):
            state.reset()

    def _append_position(
        self,
        state: WanderingTrackState,
        center: Tuple[float, float],
        timestamp_ms: int,
    ) -> None:
        state.positions.append((center[0], center[1], timestamp_ms))
        cutoff_ms = timestamp_ms - int(self.thresholds.window_seconds * 1000)
        while len(state.positions) > 1 and state.positions[0][2] < cutoff_ms:
            state.positions.popleft()

    def _compute_metrics(
        self,
        state: WanderingTrackState,
        roi: Roi,
        timestamp_ms: int,
    ) -> Dict[str, float]:
        axis = self.axis_by_roi_id.get(roi.roi_id, "x")
        total_distance = 0.0
        direction_changes = 0
        moving_steps = 0
        idle_steps = 0
        last_direction_sign: Optional[int] = None
        activity_step_threshold = max(1.0, self.thresholds.min_step_pixels * 0.5)

        positions = list(state.positions)
        for index in range(1, len(positions)):
            previous_x, previous_y, _ = positions[index - 1]
            current_x, current_y, _ = positions[index]
            delta_x = current_x - previous_x
            delta_y = current_y - previous_y
            step_distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
            total_distance += step_distance

            if step_distance >= activity_step_threshold:
                moving_steps += 1
            else:
                idle_steps += 1

            axis_delta = delta_x if axis == "x" else delta_y
            if abs(axis_delta) >= self.thresholds.min_step_pixels:
                direction_sign = 1 if axis_delta > 0 else -1
                if (
                    last_direction_sign is not None
                    and direction_sign != last_direction_sign
                ):
                    direction_changes += 1
                last_direction_sign = direction_sign

        displacement = self._displacement(positions)
        path_ratio = total_distance / max(displacement, 1.0)
        round_trips = direction_changes // 2
        total_steps = max(len(positions) - 1, 1)
        idle_ratio = idle_steps / total_steps
        axis_excursion = self._axis_excursion(positions, axis=axis)
        dwell_seconds = 0.0
        if state.episode_started_at_ms is not None:
            dwell_seconds = (timestamp_ms - state.episode_started_at_ms) / 1000.0
        window_span_seconds = 0.0
        if len(positions) >= 2:
            window_span_seconds = (positions[-1][2] - positions[0][2]) / 1000.0

        return {
            "dwell_seconds": dwell_seconds,
            "round_trips": float(round_trips),
            "direction_changes": float(direction_changes),
            "path_ratio": path_ratio,
            "total_distance_pixels": total_distance,
            "displacement_pixels": displacement,
            "axis_excursion_pixels": axis_excursion,
            "idle_ratio": idle_ratio,
            "moving_steps": float(moving_steps),
            "idle_steps": float(idle_steps),
            "window_span_seconds": window_span_seconds,
        }

    def _should_emit_event(
        self,
        state: WanderingTrackState,
        metrics: Dict[str, float],
        timestamp_ms: int,
    ) -> bool:
        if state.episode_started_at_ms is None:
            return False
        if self._is_in_cooldown(state, timestamp_ms):
            return False
        if metrics["dwell_seconds"] < self.thresholds.min_dwell_seconds:
            return False
        if metrics["round_trips"] < self.thresholds.min_round_trips:
            return False
        if metrics["direction_changes"] < self.thresholds.min_direction_changes:
            return False
        if metrics["path_ratio"] < self.thresholds.min_path_to_displacement_ratio:
            return False
        if metrics["total_distance_pixels"] < self.thresholds.min_total_distance_pixels:
            return False
        if metrics["axis_excursion_pixels"] < self.thresholds.min_axis_excursion_pixels:
            return False
        if metrics["idle_ratio"] > self.thresholds.max_idle_ratio:
            return False
        if state.last_event_timestamp_ms is None:
            return True
        return (
            metrics["round_trips"] > state.last_event_round_trips
            or metrics["direction_changes"] >= state.last_event_direction_changes + 2
        )

    def _find_roi(self, center: Tuple[float, float]) -> Optional[Roi]:
        for roi in self.roi_config.rois:
            if not self._roi_supports_wandering(roi):
                continue
            if self._point_in_polygon(center, roi.points):
                return roi
        return None

    def _roi_supports_wandering(self, roi: Roi) -> bool:
        if not roi.event_types:
            return True
        supported = {value.lower() for value in roi.event_types}
        return bool(
            {"all", "wandering", EventType.WANDERING_SUSPECTED.value}.intersection(
                supported
            )
        )

    def _point_in_polygon(
        self,
        point: Tuple[float, float],
        polygon: Sequence[Sequence[int]],
    ) -> bool:
        x, y = point
        inside = False
        point_count = len(polygon)
        if point_count < 3:
            return False

        j = point_count - 1
        for i in range(point_count):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            intersects = ((yi > y) != (yj > y)) and (
                x < ((xj - xi) * (y - yi) / max(yj - yi, 1e-6)) + xi
            )
            if intersects:
                inside = not inside
            j = i
        return inside

    def _motion_anchor(self, observation: TrackObservation) -> Tuple[float, float]:
        return ((observation.x1 + observation.x2) / 2.0, observation.y2)

    def _dominant_axis(self, polygon: Sequence[Sequence[int]]) -> str:
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        return "x" if width >= height else "y"

    def _displacement(self, positions: Sequence[PositionSample]) -> float:
        if len(positions) < 2:
            return 0.0
        start_x, start_y, _ = positions[0]
        end_x, end_y, _ = positions[-1]
        dx = end_x - start_x
        dy = end_y - start_y
        return (dx * dx + dy * dy) ** 0.5

    def _axis_excursion(
        self,
        positions: Sequence[PositionSample],
        *,
        axis: str,
    ) -> float:
        if len(positions) < 2:
            return 0.0
        if axis == "x":
            values = [sample[0] for sample in positions]
        else:
            values = [sample[1] for sample in positions]
        return max(values) - min(values)

    def _relink_recent_episode(
        self,
        *,
        track_id: int,
        roi_id: str,
        center: Tuple[float, float],
        timestamp_ms: int,
    ) -> Optional[WanderingTrackState]:
        current_state = self.track_states.get(track_id)
        if current_state is not None and current_state.active_roi_id == roi_id:
            return current_state

        relink_gap_ms = int(
            max(
                self.thresholds.max_track_gap_seconds,
                self.thresholds.reentry_grace_seconds,
            )
            * 1000
        )
        best_candidate_track_id: Optional[int] = None
        best_candidate_state: Optional[WanderingTrackState] = None
        best_distance: Optional[float] = None

        for candidate_track_id, candidate_state in list(self.track_states.items()):
            if candidate_track_id == track_id:
                continue
            if candidate_state.active_roi_id != roi_id:
                continue
            if candidate_state.last_seen_at_ms is None:
                continue
            if not candidate_state.positions:
                continue

            gap_ms = timestamp_ms - candidate_state.last_seen_at_ms
            if gap_ms < 0 or gap_ms > relink_gap_ms:
                continue

            last_x, last_y, _ = candidate_state.positions[-1]
            distance = hypot(center[0] - last_x, center[1] - last_y)
            if distance > self.thresholds.max_relink_distance_pixels:
                continue

            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_candidate_track_id = candidate_track_id
                best_candidate_state = candidate_state

        if best_candidate_track_id is None or best_candidate_state is None:
            return current_state

        self.track_states[track_id] = best_candidate_state
        del self.track_states[best_candidate_track_id]
        return best_candidate_state

    def _is_in_cooldown(self, state: WanderingTrackState, timestamp_ms: int) -> bool:
        if state.last_event_timestamp_ms is None:
            return False
        cooldown_ms = int(self.thresholds.cooldown_seconds * 1000)
        return (timestamp_ms - state.last_event_timestamp_ms) < cooldown_ms

    def _build_event(
        self,
        camera_id: str,
        observation: TrackObservation,
        track_id: int,
        roi_id: str,
        timestamp_ms: int,
        metrics: Dict[str, float],
        axis: str,
    ) -> EventRecord:
        confidence = self._compute_confidence(metrics)
        timestamp = datetime.now().astimezone()
        event_id = "wandering_{camera}_{track}_{ts}".format(
            camera=camera_id,
            track=track_id,
            ts=timestamp_ms,
        )
        return EventRecord(
            event_id=event_id,
            camera_id=camera_id,
            track_id=track_id,
            event_type=EventType.WANDERING_SUSPECTED,
            started_at=timestamp,
            ended_at=timestamp,
            source_timestamp_ms=timestamp_ms,
            confidence=confidence,
            roi_id=roi_id,
            description="배회 의심: 동일 구역 내 반복 이동이 지속됨",
            details={
                "phase": "WANDERING_SUSPECTED",
                "target_bbox": [
                    round(observation.x1, 3),
                    round(observation.y1, 3),
                    round(observation.x2, 3),
                    round(observation.y2, 3),
                ],
                "axis": axis,
                "dwell_seconds": round(metrics["dwell_seconds"], 3),
                "round_trips": int(metrics["round_trips"]),
                "direction_changes": int(metrics["direction_changes"]),
                "path_ratio": round(metrics["path_ratio"], 3),
                "total_distance_pixels": round(metrics["total_distance_pixels"], 3),
                "displacement_pixels": round(metrics["displacement_pixels"], 3),
                "axis_excursion_pixels": round(metrics["axis_excursion_pixels"], 3),
                "idle_ratio": round(metrics["idle_ratio"], 3),
                "window_span_seconds": round(metrics["window_span_seconds"], 3),
            },
        )

    def _compute_confidence(self, metrics: Dict[str, float]) -> float:
        dwell_score = min(1.0, metrics["dwell_seconds"] / self.thresholds.min_dwell_seconds)
        round_trip_score = min(
            1.0, metrics["round_trips"] / max(self.thresholds.min_round_trips, 1)
        )
        direction_score = min(
            1.0,
            metrics["direction_changes"] / max(self.thresholds.min_direction_changes, 1),
        )
        path_ratio_score = min(
            1.0,
            metrics["path_ratio"] / self.thresholds.min_path_to_displacement_ratio,
        )
        distance_score = min(
            1.0,
            metrics["total_distance_pixels"]
            / max(self.thresholds.min_total_distance_pixels, 1.0),
        )
        excursion_target = max(self.thresholds.min_axis_excursion_pixels, 1.0)
        excursion_score = min(
            1.0,
            metrics["axis_excursion_pixels"] / excursion_target,
        )
        activity_target = max(0.05, 1.0 - self.thresholds.max_idle_ratio)
        activity_score = min(1.0, max(0.0, 1.0 - metrics["idle_ratio"]) / activity_target)
        return round(
            (
                dwell_score
                + round_trip_score
                + direction_score
                + path_ratio_score
                + distance_score
                + excursion_score
                + activity_score
            )
            / 7.0,
            3,
        )
