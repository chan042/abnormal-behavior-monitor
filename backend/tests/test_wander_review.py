from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.evaluation.wander_review import load_review_targets_from_evaluation


class WanderReviewTest(unittest.TestCase):
    def test_load_review_targets_from_evaluation_filters_tp_and_fp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evaluation_summary.json"
            path.write_text(
                json.dumps(
                    {
                        "results": [
                            {"segment_id": "seg_tp_1", "status": "tp"},
                            {"segment_id": "seg_fp_1", "status": "fp"},
                            {"segment_id": "seg_fn_1", "status": "fn"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            targets = load_review_targets_from_evaluation(path)
            self.assertEqual(
                [(target.review_label, target.segment_id) for target in targets],
                [("tp", "seg_tp_1"), ("fp", "seg_fp_1")],
            )

            fp_only = load_review_targets_from_evaluation(
                path,
                include_tp=False,
                include_fp=True,
            )
            self.assertEqual(
                [(target.review_label, target.segment_id) for target in fp_only],
                [("fp", "seg_fp_1")],
            )


if __name__ == "__main__":
    unittest.main()
