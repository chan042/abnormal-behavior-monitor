from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.swoon_dataset import (
    build_fall_evaluation_segments,
    parse_swoon_dataset,
)


SAMPLE_XML = """<?xml version='1.0' encoding='utf-8'?>
<annotation>
    <folder>swoon</folder>
    <filename>101-3_cam01_swoon01_place03_day_summer.mp4</filename>
    <size>
        <width>3840</width>
        <height>2160</height>
        <depth>3</depth>
    </size>
    <header>
        <duration>00:05:11.2</duration>
        <fps>30</fps>
        <frames>9337</frames>
        <inout>IN</inout>
        <location>PLACE03</location>
        <season>SUMMER</season>
        <weather>SUNNY</weather>
        <time>DAY</time>
        <population>1</population>
        <character>F30</character>
    </header>
    <event>
        <eventname>swoon</eventname>
        <starttime>00:01:50.9</starttime>
        <duration>00:00:26.2</duration>
    </event>
    <object>
        <objectname>person_1</objectname>
        <position>
            <keyframe>3330</keyframe>
            <keypoint>
                <x>3231</x>
                <y>951</y>
            </keypoint>
        </position>
        <action>
            <actionname>totter</actionname>
            <frame>
                <start>3330</start>
                <end>3735</end>
            </frame>
        </action>
        <action>
            <actionname>falldown</actionname>
            <frame>
                <start>3735</start>
                <end>3809</end>
            </frame>
            <frame>
                <start>3809</start>
                <end>4111</end>
            </frame>
        </action>
    </object>
</annotation>
"""


class SwoonDatasetTest(unittest.TestCase):
    def test_parse_swoon_dataset_and_build_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_root = Path(temp_dir) / "swoon_sample_1" / "101-3_swoon01_place03_day"
            dataset_root.mkdir(parents=True, exist_ok=True)
            xml_path = dataset_root / "101-3_cam01_swoon01_place03_day_summer.xml"
            video_path = dataset_root / "101-3_cam01_swoon01_place03_day_summer.mp4"
            xml_path.write_text(SAMPLE_XML, encoding="utf-8")
            video_path.write_bytes(b"")

            records = parse_swoon_dataset(dataset_root.parent, project_root=Path(temp_dir))
            self.assertEqual(len(records), 1)

            record = records[0]
            self.assertEqual(record.sample_id, "101-3_cam01_swoon01_place03_day_summer")
            self.assertEqual(record.camera_id, "cam01")
            self.assertEqual(record.season, "summer")
            self.assertEqual(len(record.actions), 2)
            self.assertEqual(record.action_segments("totter")[0].start_ms, 111000)
            self.assertEqual(record.action_segments("falldown")[0].end_ms, 137033)

            segments = build_fall_evaluation_segments(records)
            self.assertEqual(len(segments), 2)
            positive_segment = next(
                segment for segment in segments if segment.segment_role == "fall_positive"
            )
            normal_segment = next(
                segment for segment in segments if segment.segment_role == "normal_pre_event"
            )

            self.assertEqual(positive_segment.label, "fall")
            self.assertEqual(positive_segment.start_ms, 119500)
            self.assertEqual(positive_segment.end_ms, 145033)
            self.assertEqual(positive_segment.totter_segments_ms, [[111000, 124500]])
            self.assertEqual(positive_segment.fall_threshold_profile, "cam01_summer")

            self.assertEqual(normal_segment.label, "normal")
            self.assertEqual(normal_segment.start_ms, 80900)
            self.assertEqual(normal_segment.end_ms, 100900)
            self.assertEqual(normal_segment.fall_threshold_profile, "cam01_summer")


if __name__ == "__main__":
    unittest.main()
