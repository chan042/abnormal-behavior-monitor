from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from backend.app.visualization.event_overlay_clips import attach_overlay_clips


class EventOverlayClipsTest(unittest.TestCase):
    def test_attach_overlay_clips_updates_event_log_and_writes_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            overlay_video = temp_path / "overlay.mp4"
            event_log = temp_path / "events.jsonl"
            output_root = temp_path / "overlay_events"

            writer = cv2.VideoWriter(
                str(overlay_video),
                cv2.VideoWriter_fourcc(*"mp4v"),
                5.0,
                (160, 120),
            )
            try:
                for index in range(40):
                    frame = np.full((120, 160, 3), index, dtype=np.uint8)
                    writer.write(frame)
            finally:
                writer.release()

            payload = {
                "event_id": "fall_cam_test_1_4000",
                "camera_id": "cam_test",
                "track_id": 1,
                "event_type": "fall_suspected",
                "started_at": "2026-04-02T23:00:00+09:00",
                "ended_at": "2026-04-02T23:00:00+09:00",
                "source_timestamp_ms": 4000,
                "confidence": 0.8,
                "roi_id": None,
                "clip_path": None,
                "snapshot_path": None,
                "description": "test",
                "status": "new",
            }
            event_log.write_text(
                json.dumps(payload, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            with patch(
                "backend.app.visualization.event_overlay_clips.transcode_mp4_for_web",
                return_value=True,
            ) as mock_transcode:
                summary = attach_overlay_clips(
                    overlay_video_path=overlay_video,
                    event_log_path=event_log,
                    output_root=output_root,
                    pre_event_seconds=1.0,
                    post_event_seconds=1.0,
                )

            self.assertEqual(summary["overlay_event_clips_written"], 1)
            updated_payload = json.loads(event_log.read_text(encoding="utf-8").strip())
            overlay_clip_path = Path(updated_payload["overlay_clip_path"])
            self.assertTrue(overlay_clip_path.exists())
            self.assertGreater(overlay_clip_path.stat().st_size, 0)
            mock_transcode.assert_called_once_with(overlay_clip_path)

            capture = cv2.VideoCapture(str(overlay_clip_path))
            try:
                self.assertTrue(capture.isOpened())
                self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0), 10)
            finally:
                capture.release()


if __name__ == "__main__":
    unittest.main()
