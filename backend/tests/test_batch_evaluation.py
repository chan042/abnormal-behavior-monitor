from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.batch import (
    run_fall_batch_evaluation,
    score_fall_segment,
    summarize_segment_results,
)
from backend.app.evaluation.swoon_dataset import EvaluationSegment, write_jsonl


class BatchEvaluationTest(unittest.TestCase):
    def test_score_fall_segment_marks_tp_and_fp(self) -> None:
        positive = EvaluationSegment(
            segment_id="sample_fall",
            sample_id="sample",
            take_id="101-1",
            camera_id="cam01",
            season="spring",
            label="fall",
            segment_role="fall_positive",
            video_path="data/samples/sample.mp4",
            xml_path="data/samples/sample.xml",
            start_ms=1000,
            end_ms=20000,
            event_start_ms=5000,
            event_end_ms=18000,
            falldown_start_ms=7000,
            falldown_end_ms=9000,
            falldown_segments_ms=[[7000, 9000]],
            totter_segments_ms=[],
        )
        negative = EvaluationSegment(
            segment_id="sample_normal",
            sample_id="sample",
            take_id="101-1",
            camera_id="cam01",
            season="spring",
            label="normal",
            segment_role="normal_pre_event",
            video_path="data/samples/sample.mp4",
            xml_path="data/samples/sample.xml",
            start_ms=0,
            end_ms=5000,
            event_start_ms=7000,
            event_end_ms=9000,
            falldown_start_ms=7000,
            falldown_end_ms=9000,
            falldown_segments_ms=[[7000, 9000]],
            totter_segments_ms=[],
        )

        tp = score_fall_segment(
            positive,
            [{"event_type": "fall_suspected", "source_timestamp_ms": 10500}],
        )
        fp = score_fall_segment(
            negative,
            [{"event_type": "fall_suspected", "source_timestamp_ms": 3200}],
        )
        summary = summarize_segment_results([tp, fp])

        self.assertEqual(tp.status, "tp")
        self.assertEqual(tp.detection_delay_ms, 3500)
        self.assertEqual(fp.status, "fp")
        self.assertEqual(summary["tp"], 1)
        self.assertEqual(summary["fp"], 1)

    def test_run_fall_batch_evaluation_uses_runner_and_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            manifest_path = temp_root / "segments.jsonl"
            output_path = temp_root / "summary.json"
            artifact_root = temp_root / "artifacts"
            video_path = temp_root / "video.mp4"
            video_path.write_bytes(b"")

            segments = [
                EvaluationSegment(
                    segment_id="sample_fall",
                    sample_id="sample",
                    take_id="101-1",
                    camera_id="cam01",
                    season="spring",
                    label="fall",
                segment_role="fall_positive",
                video_path=str(video_path),
                xml_path="sample.xml",
                start_ms=1000,
                end_ms=20000,
                    event_start_ms=5000,
                    event_end_ms=18000,
                falldown_start_ms=7000,
                falldown_end_ms=9000,
                falldown_segments_ms=[[7000, 9000]],
                totter_segments_ms=[],
                fall_threshold_profile="cam01_spring",
            ),
            EvaluationSegment(
                segment_id="sample_normal",
                sample_id="sample",
                take_id="101-1",
                    camera_id="cam01",
                    season="spring",
                    label="normal",
                    segment_role="normal_pre_event",
                    video_path=str(video_path),
                    xml_path="sample.xml",
                    start_ms=0,
                    end_ms=5000,
                    event_start_ms=7000,
                    event_end_ms=9000,
                falldown_start_ms=7000,
                falldown_end_ms=9000,
                falldown_segments_ms=[[7000, 9000]],
                totter_segments_ms=[],
                fall_threshold_profile="cam01_spring",
            ),
        ]
            write_jsonl((segment.to_dict() for segment in segments), manifest_path)

            def fake_runner(**kwargs):
                event_output_path = kwargs["event_output_path"]
                event_output_path.parent.mkdir(parents=True, exist_ok=True)
                segment_name = kwargs["camera_config"].name
                if segment_name == "sample_fall":
                    self.assertEqual(
                        kwargs["camera_config"].fall_threshold_profile,
                        "cam01_spring",
                    )
                payloads = []
                if segment_name == "sample_fall":
                    payloads.append(
                        {
                            "event_type": "fall_suspected",
                            "source_timestamp_ms": 10100,
                        }
                    )
                elif segment_name == "sample_normal":
                    payloads.append(
                        {
                            "event_type": "fall_suspected",
                            "source_timestamp_ms": 3000,
                        }
                    )
                with event_output_path.open("w", encoding="utf-8") as handle:
                    for payload in payloads:
                        handle.write(json.dumps(payload) + "\n")
                return {"events_written": len(payloads)}

            summary = run_fall_batch_evaluation(
                manifest_path,
                output_path=output_path,
                artifact_root=artifact_root,
                runner=fake_runner,
            )

            self.assertEqual(summary["summary"]["tp"], 1)
            self.assertEqual(summary["summary"]["fp"], 1)
            self.assertTrue(output_path.exists())
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted["results"]), 2)


if __name__ == "__main__":
    unittest.main()
