from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from backend.app.visualization.overlay_renderer import render_overlay_video


class OverlayRendererTest(unittest.TestCase):
    def test_render_overlay_video_creates_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_video = temp_path / "sample.mp4"
            camera_config = temp_path / "camera.yaml"
            tracking_log = temp_path / "tracking.jsonl"
            pose_log = temp_path / "pose.jsonl"
            event_log = temp_path / "events.jsonl"
            overlay_output = temp_path / "overlay.mp4"

            writer = cv2.VideoWriter(
                str(source_video),
                cv2.VideoWriter_fourcc(*"mp4v"),
                4.0,
                (160, 120),
            )
            try:
                for _ in range(4):
                    frame = np.full((120, 160, 3), 230, dtype=np.uint8)
                    writer.write(frame)
            finally:
                writer.release()

            camera_config.write_text(
                "\n".join(
                    [
                        "camera_id: cam_overlay_test",
                        "name: overlay_test",
                        "source_type: file",
                        f"source: {source_video}",
                        "enabled: true",
                        "target_fps: 4",
                        "frame_width: 160",
                        "frame_height: 120",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            tracking_payload = {
                "frame_index": 0,
                "timestamp_ms": 0,
                "track_id": 1,
                "class_id": 0,
                "class_name": "person",
                "confidence": 0.9,
                "bbox": [30.0, 20.0, 90.0, 110.0],
                "camera_id": "cam_overlay_test",
            }
            tracking_log.write_text(
                json.dumps(tracking_payload, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            pose_payload = {
                "frame_index": 0,
                "timestamp_ms": 0,
                "track_id": 1,
                "pose_confidence": 0.8,
                "pose_landmarks": [
                    {"index": 11, "x": 45.0, "y": 40.0, "z": 0.0, "visibility": 0.9},
                    {"index": 12, "x": 70.0, "y": 40.0, "z": 0.0, "visibility": 0.9},
                    {"index": 23, "x": 50.0, "y": 80.0, "z": 0.0, "visibility": 0.9},
                    {"index": 24, "x": 68.0, "y": 80.0, "z": 0.0, "visibility": 0.9},
                    {"index": 25, "x": 52.0, "y": 100.0, "z": 0.0, "visibility": 0.9},
                    {"index": 26, "x": 66.0, "y": 100.0, "z": 0.0, "visibility": 0.9},
                ],
                "camera_id": "cam_overlay_test",
            }
            pose_log.write_text(
                json.dumps(pose_payload, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            event_payload = {
                "event_id": "fall_cam_overlay_test_1_0",
                "camera_id": "cam_overlay_test",
                "track_id": 1,
                "event_type": "fall_suspected",
                "started_at": "2026-04-02T23:00:00+09:00",
                "ended_at": "2026-04-02T23:00:00+09:00",
                "source_timestamp_ms": 0,
                "confidence": 0.77,
                "roi_id": None,
                "clip_path": None,
                "snapshot_path": None,
                "description": "test",
                "status": "new",
            }
            event_log.write_text(
                json.dumps(event_payload, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            summary = render_overlay_video(
                camera_config_path=camera_config,
                tracking_log_path=tracking_log,
                pose_log_path=pose_log,
                event_log_path=event_log,
                output_path=overlay_output,
            )

            self.assertEqual(summary["frames_rendered"], 4)
            self.assertEqual(summary["frames_with_tracks"], 1)
            self.assertEqual(summary["frames_with_pose"], 1)
            self.assertTrue(overlay_output.exists())
            self.assertGreater(overlay_output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
