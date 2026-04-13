from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.live.service import LiveMonitorService


class LiveMonitorServiceTest(unittest.TestCase):
    def test_camera_summary_tracks_fall_and_wandering_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            camera_config_path = temp_path / "camera.yaml"
            camera_config_path.write_text(
                "\n".join(
                    [
                        "camera_id: cam_live_test",
                        "name: live_test",
                        "source_type: file",
                        "source: data/samples/live_test.mp4",
                        "enabled: true",
                        "target_fps: 6",
                        "frame_width: 1280",
                        "frame_height: 720",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            service = LiveMonitorService(
                camera_configs=[camera_config_path],
                enable_pose=False,
                enable_fall=False,
                enable_wandering=False,
            )
            service._update_state(
                camera_id="cam_live_test",
                stream_status="online",
                total_events_delta=3,
                fall_events_delta=1,
                wandering_events_delta=2,
            )

            summary = service.get_camera_summaries()[0]
            state = service.get_state("cam_live_test")

            self.assertEqual(summary["total_events"], 3)
            self.assertEqual(summary["fall_events"], 1)
            self.assertEqual(summary["wandering_events"], 2)
            self.assertEqual(state["fall_event_count"], 1)
            self.assertEqual(state["wandering_event_count"], 2)


if __name__ == "__main__":
    unittest.main()
