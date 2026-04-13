from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from backend.app.events.clip_manager import EventClipManager
from backend.app.events.schema import EventRecord, EventType
from backend.app.ingestion.frame_source import FramePacket


class EventClipManagerTest(unittest.TestCase):
    def test_register_event_creates_clip_and_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            clip_root = temp_path / "clips"
            snapshot_root = temp_path / "snapshots"
            with patch(
                "backend.app.events.clip_manager.transcode_mp4_for_web",
                return_value=True,
            ):
                manager = EventClipManager(
                    clip_root=clip_root,
                    snapshot_root=snapshot_root,
                    target_fps=4,
                    pre_event_seconds=1.0,
                    post_event_seconds=1.0,
                )

                for index in range(8):
                    frame = np.full((120, 160, 3), fill_value=index * 10, dtype=np.uint8)
                    manager.on_frame(
                        FramePacket(
                            frame_index=index,
                            timestamp_ms=index * 250,
                            frame=frame,
                        )
                    )
                    if index == 3:
                        event = EventRecord(
                            event_id="evt_test_001",
                            camera_id="cam_01",
                            track_id=7,
                            event_type=EventType.FALL_SUSPECTED,
                            started_at=datetime.fromtimestamp(0.75, tz=timezone.utc),
                        )
                        manager.register_event(event)

                manager.close()

            clip_path = clip_root / "cam_01" / "evt_test_001.mp4"
            snapshot_path = snapshot_root / "cam_01" / "evt_test_001.jpg"
            self.assertTrue(clip_path.exists())
            self.assertTrue(snapshot_path.exists())

            capture = cv2.VideoCapture(str(clip_path))
            try:
                self.assertTrue(capture.isOpened())
                self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0), 8)
            finally:
                capture.release()


if __name__ == "__main__":
    unittest.main()
