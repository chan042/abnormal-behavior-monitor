from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ..config import Roi, RoiConfig, load_roi_config, load_yaml_file
from ..events.schema import EventRecord, EventType
from ..tracking.types import TrackObservation


@dataclass
class WanderingThresholds:
    min_dwell_seconds: float
    min_round_trips: int
    min_direction_changes: int
    min_path_to_displacement_ratio: float
    cooldown_seconds: float
    min_step_pixels: float = 12.0

    @classmethod
    def from_yaml(cls, path: Path) -> "WanderingThresholds":
        payload = load_yaml_file(path)
        return cls(
            min_dwell_seconds=float(payload["min_dwell_seconds"]),
            min_round_trips=int(payload["min_round_trips"]),
            min_direction_changes=int(payload["min_direction_changes"]),
            min_path_to_displacement_ratio=float(payload["min_path_to_displacement_ratio"]),
            cooldown_seconds=float(payload["cooldown_seconds"]),
            min_step_pixels=float(payload.get("min_step_pixels", 12.0)),
        )


@dataclass
class WanderingTrackState:
    active_roi_id: Optional[str] = None
    roi_entered_at_ms: Optional[int] = None
    positions: List[Tuple[float, float, int]] = field(default_factory=list)
    last_direction_sign: Optional[int] = None
    direction_changes: int = 0
    round_trips: int = 0
    total_path_distance: float = 0.0
    last_event_timestamp_ms: Optional[int] = None

    def reset_for_roi(self, roi_id: Optional[str], timestamp_ms: Optional[int]) -> None:
        self.active_roi_id = roi_id
        self.roi_entered_at_ms = timestamp_ms
        self.positions = []
        self.last_direction_sign = None
        self.direction_changes = 0
        self.round_trips = 0
        self.total_path_distance = 0.0


class WanderingEventEngine:
    def __init__(self, roi_config: RoiConfig, thresholds: WanderingThresholds):
        self.roi_config = roi_config
        self.thresholds = thresholds
        self.track_states: Dict[int, WanderingTrackState] = {}
        self.axis_by_roi_id = {
            roi.roi_id: self._dominant_axis(roi.points) for roi in roi_config.rois
        }

    @classmethod
    def from_yaml(cls, roi_path: Path, threshold_path: Path) -> "WanderingEventEngine":
        return cls(
            roi_config=load_roi_config(roi_path),
            thresholds=WanderingThresholds.from_yaml(threshold_path),
        )

    def update(
        self,
        camera_id: str,
        observation: TrackObservation,
    ) -> List[EventRecord]:
        center = self._bbox_center(observation)
        roi = self._find_roi(center)
        state = self.track_states.setdefault(observation.track_id, WanderingTrackState())

        if roi is None:
            if state.active_roi_id is not None:
                state.reset_for_roi(None, None)
            return []

        if roi.roi_id != state.active_roi_id:
            state.reset_for_roi(roi.roi_id, observation.timestamp_ms)

        if self._is_in_cooldown(state, observation.timestamp_ms):
            self._append_position(state, roi, center, observation.timestamp_ms)
            return []

        self._append_position(state, roi, center, observation.timestamp_ms)
        if state.roi_entered_at_ms is None:
            return []

        dwell_seconds = (observation.timestamp_ms - state.roi_entered_at_ms) / 1000.0
        displacement = self._displacement(state.positions)
        path_ratio = state.total_path_distance / max(displacement, 1.0)

        if (
            dwell_seconds >= self.thresholds.min_dwell_seconds
            and state.round_trips >= self.thresholds.min_round_trips
            and state.direction_changes >= self.thresholds.min_direction_changes
            and path_ratio >= self.thresholds.min_path_to_displacement_ratio
        ):
            state.last_event_timestamp_ms = observation.timestamp_ms
            return [
                self._build_event(
                    camera_id=camera_id,
                    track_id=observation.track_id,
                    roi_id=roi.roi_id,
                    timestamp_ms=observation.timestamp_ms,
                    dwell_seconds=dwell_seconds,
                    round_trips=state.round_trips,
                    direction_changes=state.direction_changes,
                    path_ratio=path_ratio,
                )
            ]

        return []

    def _append_position(
        self,
        state: WanderingTrackState,
        roi: Roi,
        center: Tuple[float, float],
        timestamp_ms: int,
    ) -> None:
        if state.positions:
            previous_x, previous_y, _ = state.positions[-1]
            delta_x = center[0] - previous_x
            delta_y = center[1] - previous_y
            step_distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
            state.total_path_distance += step_distance

            axis = self.axis_by_roi_id.get(roi.roi_id, "x")
            axis_delta = delta_x if axis == "x" else delta_y
            if abs(axis_delta) >= self.thresholds.min_step_pixels:
                direction_sign = 1 if axis_delta > 0 else -1
                if (
                    state.last_direction_sign is not None
                    and direction_sign != state.last_direction_sign
                ):
                    state.direction_changes += 1
                    state.round_trips = state.direction_changes // 2
                state.last_direction_sign = direction_sign

        state.positions.append((center[0], center[1], timestamp_ms))

    def _find_roi(self, center: Tuple[float, float]) -> Optional[Roi]:
        for roi in self.roi_config.rois:
            if self._point_in_polygon(center, roi.points):
                return roi
        return None

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

    def _bbox_center(self, observation: TrackObservation) -> Tuple[float, float]:
        return ((observation.x1 + observation.x2) / 2.0, (observation.y1 + observation.y2) / 2.0)

    def _dominant_axis(self, polygon: Sequence[Sequence[int]]) -> str:
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        return "x" if width >= height else "y"

    def _displacement(self, positions: Sequence[Tuple[float, float, int]]) -> float:
        if len(positions) < 2:
            return 0.0
        start_x, start_y, _ = positions[0]
        end_x, end_y, _ = positions[-1]
        dx = end_x - start_x
        dy = end_y - start_y
        return (dx * dx + dy * dy) ** 0.5

    def _is_in_cooldown(self, state: WanderingTrackState, timestamp_ms: int) -> bool:
        if state.last_event_timestamp_ms is None:
            return False
        cooldown_ms = int(self.thresholds.cooldown_seconds * 1000)
        return (timestamp_ms - state.last_event_timestamp_ms) < cooldown_ms

    def _build_event(
        self,
        camera_id: str,
        track_id: int,
        roi_id: str,
        timestamp_ms: int,
        dwell_seconds: float,
        round_trips: int,
        direction_changes: int,
        path_ratio: float,
    ) -> EventRecord:
        confidence = self._compute_confidence(
            dwell_seconds=dwell_seconds,
            round_trips=round_trips,
            direction_changes=direction_changes,
            path_ratio=path_ratio,
        )
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
        )

    def _compute_confidence(
        self,
        dwell_seconds: float,
        round_trips: int,
        direction_changes: int,
        path_ratio: float,
    ) -> float:
        dwell_score = min(1.0, dwell_seconds / self.thresholds.min_dwell_seconds)
        round_trip_score = min(1.0, round_trips / max(self.thresholds.min_round_trips, 1))
        direction_score = min(
            1.0, direction_changes / max(self.thresholds.min_direction_changes, 1)
        )
        path_ratio_score = min(
            1.0, path_ratio / self.thresholds.min_path_to_displacement_ratio
        )
        return round(
            (dwell_score + round_trip_score + direction_score + path_ratio_score) / 4.0,
            3,
        )
