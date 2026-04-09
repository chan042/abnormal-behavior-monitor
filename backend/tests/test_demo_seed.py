from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.demo.seed import seed_demo_events


class DemoSeedTest(unittest.TestCase):
    def test_seed_demo_events_creates_event_records_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            event_output_path = temp_path / "events" / "demo_events.jsonl"
            clip_root = temp_path / "clips"
            snapshot_root = temp_path / "snapshots"

            summary = seed_demo_events(
                camera_id="cam_demo_test",
                event_output_path=event_output_path,
                clip_root=clip_root,
                snapshot_root=snapshot_root,
                width=320,
                height=180,
                fps=4,
            )

            self.assertEqual(summary["events_written"], 2)
            payloads = [
                json.loads(line)
                for line in event_output_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(payloads), 2)
            for payload in payloads:
                self.assertTrue(Path(payload["clip_path"]).exists())
                self.assertTrue(Path(payload["snapshot_path"]).exists())


if __name__ == "__main__":
    unittest.main()
