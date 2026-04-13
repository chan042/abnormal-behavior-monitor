from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.wander_batch import (
    run_wandering_batch_evaluation,
    score_wandering_segment,
    summarize_wandering_segment_results,
)
from backend.app.evaluation.wander_dataset import (
    WanderingEvaluationSegment,
    write_jsonl,
)


class WanderBatchEvaluationTest(unittest.TestCase):
    def test_score_wandering_segment_marks_tp_and_fp(self) -> None:
        positive = WanderingEvaluationSegment(
            segment_id="wander_positive",
            sample_id="sample",
            take_id="122-1",
            camera_id="cam01",
            place_id="place03",
            season="spring",
            label="wandering",
            segment_role="wandering_event_full",
            video_path="data/samples/sample.mp4",
            xml_path="data/samples/sample.xml",
            start_ms=45000,
            end_ms=220000,
            event_start_ms=60000,
            event_end_ms=210000,
            action_segments_ms=[[65000, 90000]],
            roi_profile_id="place03_cam01",
            wandering_threshold_profile="place03_cam01",
            metadata_warnings=[],
        )
        negative = WanderingEvaluationSegment(
            segment_id="wander_negative",
            sample_id="sample",
            take_id="122-1",
            camera_id="cam01",
            place_id="place03",
            season="spring",
            label="normal",
            segment_role="normal_pre_event",
            video_path="data/samples/sample.mp4",
            xml_path="data/samples/sample.xml",
            start_ms=0,
            end_ms=45000,
            event_start_ms=60000,
            event_end_ms=210000,
            action_segments_ms=[],
            roi_profile_id="place03_cam01",
            wandering_threshold_profile="place03_cam01",
            metadata_warnings=[],
        )

        tp = score_wandering_segment(
            positive,
            [{"event_type": "wandering_suspected", "source_timestamp_ms": 68000}],
        )
        fp = score_wandering_segment(
            negative,
            [{"event_type": "wandering_suspected", "source_timestamp_ms": 22000}],
        )
        summary = summarize_wandering_segment_results([tp, fp])

        self.assertEqual(tp.status, "tp")
        self.assertEqual(tp.detection_delay_ms, 8000)
        self.assertEqual(fp.status, "fp")
        self.assertEqual(summary["tp"], 1)
        self.assertEqual(summary["fp"], 1)

    def test_run_wandering_batch_evaluation_uses_runner_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            manifest_path = temp_root / "segments.jsonl"
            output_path = temp_root / "summary.json"
            artifact_root = temp_root / "artifacts"
            roi_root = temp_root / "rois"
            roi_root.mkdir()
            (roi_root / "place03_cam01.yaml").write_text(
                "camera_id: place03_cam01\nrois:\n  - roi_id: wander_zone\n    name: Wander Zone\n    axis: x\n    event_types: [wandering]\n    points:\n      - [0, 0]\n      - [100, 0]\n      - [100, 100]\n      - [0, 100]\n",
                encoding="utf-8",
            )
            threshold_path = temp_root / "wandering.yaml"
            threshold_path.write_text(
                "min_dwell_seconds: 30\nmin_round_trips: 2\nmin_direction_changes: 4\nmin_path_to_displacement_ratio: 2.0\ncooldown_seconds: 60\n",
                encoding="utf-8",
            )
            video_path = temp_root / "video.mp4"
            video_path.write_bytes(b"")

            segments = [
                WanderingEvaluationSegment(
                    segment_id="wander_positive",
                    sample_id="sample",
                    take_id="122-1",
                    camera_id="cam01",
                    place_id="place03",
                    season="spring",
                    label="wandering",
                    segment_role="wandering_event_full",
                    video_path=str(video_path),
                    xml_path="sample.xml",
                    start_ms=45000,
                    end_ms=220000,
                    event_start_ms=60000,
                    event_end_ms=210000,
                    action_segments_ms=[[65000, 90000]],
                    roi_profile_id="place03_cam01",
                    wandering_threshold_profile="place03_cam01",
                    metadata_warnings=[],
                ),
                WanderingEvaluationSegment(
                    segment_id="wander_negative",
                    sample_id="sample",
                    take_id="122-1",
                    camera_id="cam01",
                    place_id="place03",
                    season="spring",
                    label="normal",
                    segment_role="normal_pre_event",
                    video_path=str(video_path),
                    xml_path="sample.xml",
                    start_ms=0,
                    end_ms=45000,
                    event_start_ms=60000,
                    event_end_ms=210000,
                    action_segments_ms=[],
                    roi_profile_id="place03_cam01",
                    wandering_threshold_profile="place03_cam01",
                    metadata_warnings=[],
                ),
            ]
            write_jsonl((segment.to_dict() for segment in segments), manifest_path)

            def fake_runner(**kwargs):
                event_output_path = kwargs["event_output_path"]
                event_output_path.parent.mkdir(parents=True, exist_ok=True)
                self.assertEqual(kwargs["camera_config"].wandering_threshold_profile, "place03_cam01")
                self.assertEqual(kwargs["roi_config_path"], roi_root / "place03_cam01.yaml")
                payloads = []
                if kwargs["camera_config"].name == "wander_positive":
                    payloads.append(
                        {
                            "event_type": "wandering_suspected",
                            "source_timestamp_ms": 68000,
                        }
                    )
                with event_output_path.open("w", encoding="utf-8") as handle:
                    for payload in payloads:
                        handle.write(json.dumps(payload) + "\n")
                return {"events_written": len(payloads)}

            summary = run_wandering_batch_evaluation(
                manifest_path,
                output_path=output_path,
                roi_config_root=roi_root,
                artifact_root=artifact_root,
                wandering_threshold_path=threshold_path,
                runner=fake_runner,
            )

            self.assertEqual(summary["summary"]["tp"], 1)
            self.assertEqual(summary["summary"]["tn"], 1)
            self.assertEqual(summary["summary"]["fp"], 0)
            self.assertTrue(output_path.exists())
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["results"]), 2)


if __name__ == "__main__":
    unittest.main()
