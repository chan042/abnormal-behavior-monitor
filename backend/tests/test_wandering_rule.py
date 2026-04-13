from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.config import Roi, RoiConfig
from backend.app.rules.wandering import (
    WanderingEventEngine,
    WanderingThresholds,
    build_full_frame_roi_config,
)
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
                    axis="x",
                    event_types=["wandering"],
                )
            ],
        )
        thresholds = WanderingThresholds(
            min_dwell_seconds=1.0,
            min_round_trips=2,
            min_direction_changes=4,
            min_path_to_displacement_ratio=2.0,
            cooldown_seconds=3.0,
            min_step_pixels=5.0,
            window_seconds=30.0,
            max_track_gap_seconds=2.0,
            reentry_grace_seconds=0.5,
            min_total_distance_pixels=300.0,
            min_axis_excursion_pixels=60.0,
            max_idle_ratio=0.6,
            max_relink_distance_pixels=120.0,
        )
        self.engine = WanderingEventEngine(roi_config=roi_config, thresholds=thresholds)

    def test_emits_wandering_event_for_back_and_forth_motion(self) -> None:
        events = self._run_positions([50, 120, 220, 120, 220, 120, 220, 120])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type.value, "wandering_suspected")
        self.assertEqual(events[0].roi_id, "corridor_a")
        self.assertIsNotNone(events[0].details)
        self.assertEqual(events[0].details["round_trips"], 2)
        self.assertGreater(events[0].details["path_ratio"], 2.0)
        self.assertEqual(len(events[0].details["target_bbox"]), 4)

    def test_does_not_emit_for_straight_walkthrough(self) -> None:
        events = self._run_positions([20, 60, 100, 140, 180, 220, 260])

        self.assertEqual(events, [])

    def test_does_not_emit_for_stationary_dwell(self) -> None:
        events = self._run_positions([100, 102, 101, 103, 102, 101, 100, 102, 101])

        self.assertEqual(events, [])

    def test_does_not_emit_for_roi_boundary_flicker(self) -> None:
        events = self._run_positions([295, 304, 296, 305, 297, 304, 296, 305])

        self.assertEqual(events, [])

    def test_does_not_emit_for_small_excursion_jitter(self) -> None:
        events = self._run_positions(
            [
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
                100,
                120,
            ]
        )

        self.assertEqual(events, [])

    def test_cooldown_suppresses_duplicate_events(self) -> None:
        events = self._run_positions(
            [50, 120, 220, 120, 220, 120, 220, 120, 220, 120, 220, 120]
        )

        self.assertEqual(len(events), 1)

    def test_short_track_gap_preserves_episode(self) -> None:
        sequence = [
            (0, 50),
            (250, 120),
            (500, 220),
            (750, 120),
            (1000, 220),
            (2200, 120),
            (2450, 220),
            (2700, 120),
        ]

        events = self._run_timed_positions(sequence)

        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0].details["direction_changes"], 4)

    def test_recent_track_relink_preserves_episode_across_track_ids(self) -> None:
        sequence = [
            (0, 50, 5),
            (250, 120, 5),
            (500, 220, 5),
            (750, 120, 5),
            (1000, 220, 9),
            (1250, 120, 9),
            (1500, 220, 9),
            (1750, 120, 9),
        ]

        emitted_events = []
        for timestamp_ms, x, track_id in sequence:
            emitted_events.extend(
                self.engine.update(
                    camera_id="cam_01",
                    observation=self._make_observation(
                        timestamp_ms=timestamp_ms,
                        x=x,
                        y=100,
                        track_id=track_id,
                    ),
                )
            )

        self.assertEqual(len(emitted_events), 1)
        self.assertEqual(emitted_events[0].track_id, 9)

    def test_profile_and_roi_metadata_are_loaded_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            roi_path = temp_path / "roi.yaml"
            threshold_path = temp_path / "wandering.yaml"
            roi_path.write_text(
                "\n".join(
                    [
                        "camera_id: cam_01",
                        "rois:",
                        "  - roi_id: corridor_a",
                        "    name: Corridor A",
                        "    axis: y",
                        "    event_types: [wandering]",
                        "    points:",
                        "      - [0, 0]",
                        "      - [100, 0]",
                        "      - [100, 300]",
                        "      - [0, 300]",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            threshold_path.write_text(
                "\n".join(
                    [
                        "min_dwell_seconds: 180",
                        "min_round_trips: 3",
                        "min_direction_changes: 5",
                        "min_path_to_displacement_ratio: 2.5",
                        "cooldown_seconds: 120",
                        "profiles:",
                        "  cam_01:",
                        "    min_round_trips: 4",
                        "    min_axis_excursion_pixels: 80",
                        "    max_idle_ratio: 0.5",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            engine = WanderingEventEngine.from_yaml(
                roi_path=roi_path,
                threshold_path=threshold_path,
                profile="cam_01",
            )

            self.assertEqual(engine.axis_by_roi_id["corridor_a"], "y")
            self.assertEqual(engine.thresholds.min_round_trips, 4)
            self.assertEqual(engine.thresholds.min_axis_excursion_pixels, 80)
            self.assertEqual(engine.thresholds.max_idle_ratio, 0.5)

    def test_build_full_frame_roi_config_covers_camera_frame(self) -> None:
        roi_config = build_full_frame_roi_config(
            camera_id="cam_demo",
            frame_width=1280,
            frame_height=720,
        )

        self.assertEqual(roi_config.camera_id, "cam_demo")
        self.assertEqual(len(roi_config.rois), 1)
        self.assertEqual(
            roi_config.rois[0].points,
            [[0, 0], [1280, 0], [1280, 720], [0, 720]],
        )
        self.assertEqual(roi_config.rois[0].event_types, ["wandering"])

    def _run_positions(self, xs: list[float], y: float = 100) -> list:
        timed_positions = [(index * 250, x) for index, x in enumerate(xs)]
        return self._run_timed_positions(timed_positions, y=y)

    def _run_timed_positions(
        self,
        timed_positions: list[tuple[int, float]],
        y: float = 100,
    ) -> list:
        emitted_events = []
        for timestamp_ms, x in timed_positions:
            emitted_events.extend(
                self.engine.update(
                    camera_id="cam_01",
                    observation=self._make_observation(
                        timestamp_ms=timestamp_ms,
                        x=x,
                        y=y,
                    ),
                )
            )
        return emitted_events

    def _make_observation(
        self,
        timestamp_ms: int,
        x: float,
        y: float,
        track_id: int = 5,
    ) -> TrackObservation:
        return TrackObservation(
            frame_index=timestamp_ms // 250,
            timestamp_ms=timestamp_ms,
            track_id=track_id,
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
