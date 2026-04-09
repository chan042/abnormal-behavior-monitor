from __future__ import annotations

import unittest

from backend.app.config import Roi, RoiConfig
from backend.app.rules.wandering import WanderingEventEngine, WanderingThresholds
from backend.app.tracking.types import TrackObservation


class WanderingEventEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        roi_config = RoiConfig(
            camera_id="cam_01",
            rois=[
                Roi(
                    roi_id="corridor_a",
                    name="Corridor A",
                    points=[[0, 0], [300, 0], [300, 200], [0, 200]],
                )
            ],
        )
        thresholds = WanderingThresholds(
            min_dwell_seconds=1.0,
            min_round_trips=2,
            min_direction_changes=4,
            min_path_to_displacement_ratio=2.0,
            cooldown_seconds=30,
            min_step_pixels=5.0,
        )
        self.engine = WanderingEventEngine(roi_config=roi_config, thresholds=thresholds)

    def test_emits_wandering_event_for_back_and_forth_motion(self) -> None:
        xs = [50, 120, 220, 120, 220, 120, 220, 120]
        emitted_events = []
        for idx, x in enumerate(xs):
            emitted_events.extend(
                self.engine.update(
                    camera_id="cam_01",
                    observation=self._make_observation(timestamp_ms=idx * 250, x=x, y=100),
                )
            )

        self.assertEqual(len(emitted_events), 1)
        self.assertEqual(emitted_events[0].event_type.value, "wandering_suspected")
        self.assertEqual(emitted_events[0].roi_id, "corridor_a")

    def test_does_not_emit_for_straight_walkthrough(self) -> None:
        xs = [20, 60, 100, 140, 180, 220, 260]
        emitted_events = []
        for idx, x in enumerate(xs):
            emitted_events.extend(
                self.engine.update(
                    camera_id="cam_01",
                    observation=self._make_observation(timestamp_ms=idx * 250, x=x, y=100),
                )
            )

        self.assertEqual(emitted_events, [])

    def _make_observation(self, timestamp_ms: int, x: float, y: float) -> TrackObservation:
        return TrackObservation(
            frame_index=timestamp_ms // 250,
            timestamp_ms=timestamp_ms,
            track_id=5,
            class_id=0,
            class_name="person",
            confidence=0.92,
            x1=x - 20,
            y1=y - 40,
            x2=x + 20,
            y2=y + 40,
        )


if __name__ == "__main__":
    unittest.main()
