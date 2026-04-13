from __future__ import annotations

import unittest
from typing import List
import tempfile
from pathlib import Path

from backend.app.pose.types import PoseLandmarkRecord, PoseObservation
from backend.app.rules.fall import FallEventEngine, FallThresholds
from backend.app.tracking.types import TrackObservation


class FallEventEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=40,
                horizontal_ratio_threshold=1.2,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=5,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=60,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.0,
                horizontal_persistence_seconds=0.0,
                max_confirmation_seconds=0.0,
                min_forward_drop_pixels=0.0,
                min_forward_drop_ratio=0.0,
                min_confirmation_angle_change_degrees=0.0,
                min_episode_peak_angle_degrees=0.0,
            )
        )

    def test_emits_fall_event_for_collapse_sequence(self) -> None:
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=10, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=100, center_y=185, angle=12, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=300, center_y=320, angle=75, aspect_ratio=1.4),
            self._make_sample(timestamp_ms=450, center_y=322, angle=78, aspect_ratio=1.4),
            self._make_sample(timestamp_ms=650, center_y=323, angle=79, aspect_ratio=1.4),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(
                self.engine.update("cam_01", track_observation, pose_observation)
            )

        self.assertEqual(len(emitted_events), 1)
        self.assertEqual(emitted_events[0].camera_id, "cam_01")
        self.assertEqual(emitted_events[0].track_id, 7)
        self.assertEqual(emitted_events[0].event_type.value, "fall_suspected")
        self.assertIsNotNone(emitted_events[0].details)
        self.assertEqual(emitted_events[0].details["phase"], "FALL_CONFIRMED")
        self.assertEqual(len(emitted_events[0].details["target_bbox"]), 4)

    def test_does_not_emit_for_upright_motion(self) -> None:
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=10, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=100, center_y=220, angle=12, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=200, center_y=260, angle=15, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=300, center_y=300, angle=18, aspect_ratio=0.5),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(
                self.engine.update("cam_01", track_observation, pose_observation)
            )

        self.assertEqual(emitted_events, [])

    def test_uses_normalized_drop_for_small_subjects(self) -> None:
        engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=30,
                horizontal_ratio_threshold=1.0,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=5,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=60,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.25,
                horizontal_persistence_seconds=0.0,
                max_confirmation_seconds=0.0,
                min_forward_drop_pixels=0.0,
                min_forward_drop_ratio=0.0,
                min_confirmation_angle_change_degrees=0.0,
                min_episode_peak_angle_degrees=0.0,
            )
        )
        samples = [
            self._make_sample(
                timestamp_ms=0,
                center_y=180,
                angle=10,
                aspect_ratio=0.6,
                height=40,
            ),
            self._make_sample(
                timestamp_ms=250,
                center_y=192,
                angle=70,
                aspect_ratio=1.3,
                height=40,
            ),
            self._make_sample(
                timestamp_ms=450,
                center_y=193,
                angle=74,
                aspect_ratio=1.3,
                height=40,
            ),
            self._make_sample(
                timestamp_ms=700,
                center_y=193,
                angle=75,
                aspect_ratio=1.3,
                height=40,
            ),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(engine.update("cam_01", track_observation, pose_observation))

        self.assertEqual(len(emitted_events), 1)

    def test_requires_horizontal_persistence_before_confirming(self) -> None:
        engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=40,
                horizontal_ratio_threshold=1.2,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=5,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=60,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.0,
                horizontal_persistence_seconds=0.4,
                max_confirmation_seconds=0.0,
                min_forward_drop_pixels=0.0,
                min_forward_drop_ratio=0.0,
                min_confirmation_angle_change_degrees=0.0,
                min_episode_peak_angle_degrees=0.0,
            )
        )
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=10, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=250, center_y=320, angle=75, aspect_ratio=1.4),
            self._make_sample(timestamp_ms=400, center_y=210, angle=12, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=800, center_y=210, angle=10, aspect_ratio=0.5),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(engine.update("cam_01", track_observation, pose_observation))

        self.assertEqual(emitted_events, [])

    def test_does_not_confirm_after_confirmation_window_expires(self) -> None:
        engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=40,
                horizontal_ratio_threshold=1.2,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=5,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=60,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.0,
                horizontal_persistence_seconds=0.0,
                max_confirmation_seconds=0.5,
                min_forward_drop_pixels=0.0,
                min_forward_drop_ratio=0.0,
                min_confirmation_angle_change_degrees=0.0,
                min_episode_peak_angle_degrees=0.0,
            )
        )
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=10, aspect_ratio=0.5),
            self._make_sample(timestamp_ms=200, center_y=320, angle=75, aspect_ratio=1.4),
            self._make_sample(timestamp_ms=300, center_y=321, angle=76, aspect_ratio=1.4),
            self._make_sample(timestamp_ms=1200, center_y=322, angle=78, aspect_ratio=1.4),
            self._make_sample(timestamp_ms=1400, center_y=323, angle=79, aspect_ratio=1.4),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(engine.update("cam_01", track_observation, pose_observation))

        self.assertEqual(emitted_events, [])

    def test_does_not_confirm_horizontal_pose_without_forward_drop(self) -> None:
        engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=10,
                horizontal_ratio_threshold=0.7,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=5,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=30,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.25,
                horizontal_persistence_seconds=0.4,
                max_confirmation_seconds=25,
                min_forward_drop_pixels=5,
                min_forward_drop_ratio=0.05,
                min_confirmation_angle_change_degrees=0.0,
                min_episode_peak_angle_degrees=0.0,
            )
        )
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=10, aspect_ratio=0.8),
            self._make_sample(timestamp_ms=200, center_y=178, angle=70, aspect_ratio=0.82),
            self._make_sample(timestamp_ms=500, center_y=177, angle=72, aspect_ratio=0.85),
            self._make_sample(timestamp_ms=800, center_y=176, angle=74, aspect_ratio=0.83),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(engine.update("cam_01", track_observation, pose_observation))

        self.assertEqual(emitted_events, [])

    def test_loads_profile_override_from_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fall.yaml"
            path.write_text(
                "\n".join(
                    [
                        "center_drop_pixels: 20",
                        "angle_change_degrees: 10",
                        "horizontal_ratio_threshold: 0.7",
                        "no_motion_seconds: 0.2",
                        "cooldown_seconds: 10",
                        "profiles:",
                        "  cam01_summer:",
                        "    horizontal_ratio_threshold: 0.9",
                        "    min_forward_drop_ratio: 0.02",
                        "    min_confirmation_angle_change_degrees: 5",
                        "    min_episode_peak_angle_degrees: 50",
                    ]
                ),
                encoding="utf-8",
            )

            base = FallThresholds.from_yaml(path)
            overridden = FallThresholds.from_yaml(path, profile="cam01_summer")

            self.assertEqual(base.horizontal_ratio_threshold, 0.7)
            self.assertEqual(overridden.horizontal_ratio_threshold, 0.9)
            self.assertEqual(overridden.min_forward_drop_ratio, 0.02)
            self.assertEqual(overridden.min_confirmation_angle_change_degrees, 5.0)
            self.assertEqual(overridden.min_episode_peak_angle_degrees, 50.0)

    def test_requires_confirmation_angle_change_when_configured(self) -> None:
        engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=10,
                horizontal_ratio_threshold=0.7,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=30,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=30,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.25,
                horizontal_persistence_seconds=0.4,
                max_confirmation_seconds=25,
                min_forward_drop_pixels=0.0,
                min_forward_drop_ratio=0.0,
                min_confirmation_angle_change_degrees=5.0,
                min_episode_peak_angle_degrees=0.0,
            )
        )
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=20, aspect_ratio=0.8),
            self._make_sample(timestamp_ms=200, center_y=175, angle=34, aspect_ratio=1.35),
            self._make_sample(timestamp_ms=600, center_y=185, angle=36, aspect_ratio=1.3),
            self._make_sample(timestamp_ms=1200, center_y=190, angle=37, aspect_ratio=1.28),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(engine.update("cam_01", track_observation, pose_observation))

        self.assertEqual(emitted_events, [])

    def test_requires_episode_peak_angle_when_configured(self) -> None:
        engine = FallEventEngine(
            FallThresholds(
                center_drop_pixels=80,
                angle_change_degrees=10,
                horizontal_ratio_threshold=0.7,
                no_motion_seconds=0.2,
                cooldown_seconds=10,
                max_motion_pixels=30,
                fall_window_seconds=1.0,
                min_pose_confidence=0.1,
                horizontal_angle_threshold=30,
                upright_angle_threshold=25,
                center_drop_height_ratio=0.25,
                horizontal_persistence_seconds=0.4,
                max_confirmation_seconds=25,
                min_forward_drop_pixels=0.0,
                min_forward_drop_ratio=0.0,
                min_confirmation_angle_change_degrees=0.0,
                min_episode_peak_angle_degrees=50.0,
            )
        )
        samples = [
            self._make_sample(timestamp_ms=0, center_y=180, angle=20, aspect_ratio=0.8),
            self._make_sample(timestamp_ms=200, center_y=176, angle=34, aspect_ratio=1.35),
            self._make_sample(timestamp_ms=700, center_y=188, angle=38, aspect_ratio=1.3),
            self._make_sample(timestamp_ms=1000, center_y=191, angle=42, aspect_ratio=1.25),
        ]

        emitted_events = []
        for track_observation, pose_observation in samples:
            emitted_events.extend(engine.update("cam_01", track_observation, pose_observation))

        self.assertEqual(emitted_events, [])

    def _make_sample(
        self,
        timestamp_ms: int,
        center_y: float,
        angle: float,
        aspect_ratio: float,
        height: float = 100.0,
    ) -> tuple[TrackObservation, PoseObservation]:
        width = height * aspect_ratio
        center_x = 200.0
        x1 = center_x - (width / 2.0)
        x2 = center_x + (width / 2.0)
        y1 = center_y - (height / 2.0)
        y2 = center_y + (height / 2.0)

        track_observation = TrackObservation(
            frame_index=timestamp_ms // 100,
            timestamp_ms=timestamp_ms,
            track_id=7,
            class_id=0,
            class_name="person",
            confidence=0.95,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
        )
        pose_observation = PoseObservation(
            frame_index=timestamp_ms // 100,
            timestamp_ms=timestamp_ms,
            track_id=7,
            confidence=0.95,
            landmarks=self._make_torso_landmarks(center_x, center_y, angle),
        )
        return track_observation, pose_observation

    def _make_torso_landmarks(
        self,
        center_x: float,
        center_y: float,
        angle: float,
    ) -> List[PoseLandmarkRecord]:
        import math

        half_length = 40.0
        radians = math.radians(angle)
        delta_x = math.sin(radians) * half_length
        delta_y = math.cos(radians) * half_length

        shoulder_center_x = center_x - delta_x
        shoulder_center_y = center_y - delta_y
        hip_center_x = center_x + delta_x
        hip_center_y = center_y + delta_y

        return [
            PoseLandmarkRecord(11, shoulder_center_x - 10, shoulder_center_y, 0.0, 0.99),
            PoseLandmarkRecord(12, shoulder_center_x + 10, shoulder_center_y, 0.0, 0.99),
            PoseLandmarkRecord(23, hip_center_x - 10, hip_center_y, 0.0, 0.99),
            PoseLandmarkRecord(24, hip_center_x + 10, hip_center_y, 0.0, 0.99),
        ]


if __name__ == "__main__":
    unittest.main()
