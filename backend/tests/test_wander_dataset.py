from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.wander_dataset import (
    build_wandering_evaluation_segments,
    parse_wander_annotation,
)


def _sample_xml() -> str:
    return """<annotation>
  <header>
    <duration>00:05:00.0</duration>
    <fps>30</fps>
    <frames>9000</frames>
    <inout>indoor</inout>
    <location>place02</location>
    <season>spring</season>
    <weather>clear</weather>
    <time>DAY</time>
    <population>1</population>
    <character>subject_a</character>
  </header>
  <size>
    <width>3840</width>
    <height>2160</height>
  </size>
  <event>
    <eventname>wander</eventname>
    <starttime>00:01:00.0</starttime>
    <duration>00:02:30.0</duration>
  </event>
  <object>
    <position>
      <keyframe>1800</keyframe>
      <keypoint>
        <x>1000</x>
        <y>1200</y>
      </keypoint>
    </position>
    <action>
      <actionname>stop and go</actionname>
      <frame>
        <start>1800</start>
        <end>2400</end>
      </frame>
      <frame>
        <start>3000</start>
        <end>3600</end>
      </frame>
    </action>
  </object>
</annotation>
"""


class WanderDatasetTest(unittest.TestCase):
    def test_parse_wander_annotation_collects_profiles_and_metadata_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_root = Path(temp_dir) / "wander_sample_1"
            sample_dir = dataset_root / "122-2"
            sample_dir.mkdir(parents=True)
            xml_path = sample_dir / "122-5_cam02_wander02_place02_night_spring.xml"
            video_path = xml_path.with_suffix(".mp4")
            xml_path.write_text(_sample_xml(), encoding="utf-8")
            video_path.write_bytes(b"")

            record = parse_wander_annotation(xml_path, project_root=dataset_root.parent)

            self.assertEqual(record.sample_id, "122-5_cam02_wander02_place02_night_spring")
            self.assertEqual(record.roi_profile_id, "place02_cam02")
            self.assertEqual(record.wandering_threshold_profile, "place02_cam02")
            self.assertEqual(record.event_start_ms, 60000)
            self.assertEqual(record.event_end_ms, 210000)
            self.assertEqual(record.keyframe, 1800)
            self.assertEqual(record.keypoint_xy, [1000, 1200])
            self.assertEqual(record.video_path, "wander_sample_1/122-2/122-5_cam02_wander02_place02_night_spring.mp4")
            self.assertIn("folder_take_mismatch:122-2!=122-5", record.metadata_warnings)
            self.assertIn("time_of_day_mismatch:night!=day", record.metadata_warnings)

    def test_build_wandering_evaluation_segments_creates_positive_and_normal_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_root = Path(temp_dir) / "wander_sample_1"
            sample_dir = dataset_root / "123-1"
            sample_dir.mkdir(parents=True)
            xml_path = sample_dir / "123-1_cam01_wander02_place03_day_summer.xml"
            video_path = xml_path.with_suffix(".mp4")
            xml_path.write_text(_sample_xml().replace("place02", "place03").replace("night", "day"), encoding="utf-8")
            video_path.write_bytes(b"")

            record = parse_wander_annotation(xml_path, project_root=dataset_root.parent)
            segments = build_wandering_evaluation_segments([record])

            self.assertEqual(len(segments), 3)
            positive = next(segment for segment in segments if segment.label == "wandering")
            pre = next(segment for segment in segments if segment.segment_role == "normal_pre_event")
            post = next(segment for segment in segments if segment.segment_role == "normal_post_event")

            self.assertEqual(positive.start_ms, 45000)
            self.assertEqual(positive.end_ms, 220000)
            self.assertEqual(pre.start_ms, 10000)
            self.assertEqual(pre.end_ms, 55000)
            self.assertEqual(post.start_ms, 215000)
            self.assertEqual(post.end_ms, 260000)
            self.assertEqual(positive.action_segments_ms, [[60000, 120000]])


if __name__ == "__main__":
    unittest.main()
