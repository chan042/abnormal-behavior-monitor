from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.review import load_review_targets


class ReviewTest(unittest.TestCase):
    def test_load_review_targets_respects_candidate_and_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tuning_summary.json"
            path.write_text(
                json.dumps(
                    {
                        "candidate_a": {
                            "tp_segments": ["seg_tp_1", "seg_tp_2"],
                            "fp_segments": ["seg_fp_1"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            targets = load_review_targets(path, "candidate_a")
            self.assertEqual(
                [(target.review_label, target.segment_id) for target in targets],
                [("tp", "seg_tp_1"), ("tp", "seg_tp_2"), ("fp", "seg_fp_1")],
            )

            fp_only = load_review_targets(
                path,
                "candidate_a",
                include_tp=False,
                include_fp=True,
            )
            self.assertEqual(
                [(target.review_label, target.segment_id) for target in fp_only],
                [("fp", "seg_fp_1")],
            )


if __name__ == "__main__":
    unittest.main()
