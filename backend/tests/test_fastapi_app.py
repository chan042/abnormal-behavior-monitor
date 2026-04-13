from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.fastapi_app import create_fastapi_app
from backend.app.events.schema import EventRecord, EventType


class FakeLiveMonitor:
    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False

    def get_camera_summaries(self):
        return [
            {
                "camera_id": "cam_live_01",
                "name": "라이브 카메라",
                "location": "라이브 입력",
                "zone_label": "라이브 구역",
                "stream_status": "online",
                "status_source": "live_monitor",
                "source_type": "camera",
                "live_supported": True,
                "live_frame_url": "/api/live/cameras/cam_live_01/frame",
                "live_stream_url": "/api/live/cameras/cam_live_01/stream",
                "last_seen_at": None,
                "total_events": 0,
                "unreviewed_events": 0,
                "fall_events": 0,
                "wandering_events": 0,
                "latest_event_id": None,
                "latest_event_type": None,
                "latest_event_status": "new",
                "latest_event_started_at": None,
                "latest_confidence": None,
                "preview_snapshot_url": "/api/live/cameras/cam_live_01/frame",
                "preview_clip_url": "/api/live/cameras/cam_live_01/stream",
                "detail_event_url": None,
                "input_fps": 6,
                "inference_fps": 6,
                "processing_delay_ms": None,
            }
        ]

    def get_summary_fragment(self):
        return {
            "camera_total": 1,
            "camera_online": 1,
            "camera_attention": 0,
        }

    def has_camera(self, camera_id):
        return camera_id == "cam_live_01"

    def get_latest_frame(self, camera_id):
        if camera_id != "cam_live_01":
            return None
        return b"\xff\xd8\xff\xd9"

    def get_state(self, camera_id):
        if camera_id != "cam_live_01":
            return None
        return {"camera_id": camera_id, "stream_status": "online"}


class FakeBrowserLiveService:
    def get_camera_summaries(self):
        return [
            {
                "camera_id": "browser_desktop_main",
                "name": "브라우저 카메라",
                "location": "브라우저 입력",
                "zone_label": "브라우저 카메라",
                "stream_status": "online",
                "status_source": "browser_live",
                "source_type": "browser",
                "live_supported": True,
                "live_frame_url": None,
                "live_stream_url": None,
                "last_seen_at": None,
                "total_events": 0,
                "unreviewed_events": 0,
                "fall_events": 0,
                "wandering_events": 0,
                "latest_event_id": None,
                "latest_event_type": None,
                "latest_event_status": "",
                "latest_event_started_at": None,
                "latest_confidence": None,
                "preview_snapshot_url": None,
                "preview_clip_url": None,
                "detail_event_url": None,
                "input_fps": 4,
                "inference_fps": 4,
                "processing_delay_ms": None,
            }
        ]

    def get_session_summaries(self):
        return [
            {
                "session_id": "browser_desktop_main",
                "frame_index": 3,
                "track_count": 1,
                "pose_count": 1,
                "event_count": 0,
                "last_error": None,
            }
        ]

    def infer_jpeg_frame(self, session_id, frame_bytes, timestamp_ms=None, camera_label=None):
        return {
            "session_id": session_id,
            "camera_label": camera_label,
            "frame_index": 4,
            "timestamp_ms": timestamp_ms,
            "image_width": 960,
            "image_height": 540,
            "tracks": [
                {
                    "frame_index": 4,
                    "timestamp_ms": timestamp_ms,
                    "track_id": 7,
                    "class_id": 0,
                    "class_name": "person",
                    "confidence": 0.8,
                    "bbox": [10, 20, 110, 220],
                }
            ],
            "poses": [],
            "events": [],
            "processing_at": "2026-04-06T00:00:00+00:00",
            "last_error": None,
        }

    def reset(self, session_id=None):
        return {"reset": True, "session_id": session_id}


class FastApiAppTest(unittest.TestCase):
    def test_event_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_root = Path(temp_dir) / "events"
            event_root.mkdir(parents=True, exist_ok=True)
            event_file = event_root / "events.jsonl"
            clip_path = Path(temp_dir) / "sample.mp4"
            clip_path.write_bytes(b"0123456789abcdef")
            event = EventRecord(
                event_id="evt_fastapi_01",
                camera_id="cam_api",
                track_id=9,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(100, tz=timezone.utc),
                clip_path=str(clip_path),
            )
            event_file.write_text(
                json.dumps(event.to_dict(), ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            client = TestClient(create_fastapi_app(event_root=event_root))
            response = client.get("/api/events")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 1)
            self.assertEqual(response.json()["items"][0]["description_status"], "fallback")

            summary = client.get("/api/summary")
            self.assertEqual(summary.status_code, 200)
            self.assertEqual(summary.json()["events"]["total"], 1)
            self.assertIsNotNone(summary.json()["latest_updated_at"])

            update = client.post(
                "/api/events/evt_fastapi_01/status",
                json={"status": "confirmed", "operator_note": "확인 완료"},
            )
            self.assertEqual(update.status_code, 200)
            self.assertEqual(update.json()["status"], "confirmed")
            self.assertIsNotNone(update.json()["updated_at"])
            refreshed_summary = client.get("/api/summary")
            self.assertEqual(refreshed_summary.status_code, 200)
            self.assertIsNotNone(refreshed_summary.json()["latest_updated_at"])

            clip = client.get("/api/events/evt_fastapi_01/clip")
            self.assertEqual(clip.status_code, 200)
            self.assertEqual(clip.headers["content-type"], "video/mp4")

    def test_live_and_browser_live_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_root = Path(temp_dir) / "events"
            event_root.mkdir(parents=True, exist_ok=True)
            app = create_fastapi_app(
                event_root=event_root,
                live_monitor=FakeLiveMonitor(),
                browser_live_service=FakeBrowserLiveService(),
            )
            client = TestClient(app)

            summary = client.get("/api/summary")
            self.assertEqual(summary.status_code, 200)
            self.assertEqual(summary.json()["cameras"]["total"], 2)

            merged_cameras = client.get("/api/cameras")
            self.assertEqual(merged_cameras.status_code, 200)
            self.assertEqual(merged_cameras.json()["count"], 2)

            cameras = client.get("/api/live/cameras")
            self.assertEqual(cameras.status_code, 200)
            self.assertEqual(cameras.json()["count"], 1)

            frame = client.get("/api/live/cameras/cam_live_01/frame")
            self.assertEqual(frame.status_code, 200)
            self.assertEqual(frame.headers["content-type"], "image/jpeg")

            sessions = client.get("/api/browser-live/sessions")
            self.assertEqual(sessions.status_code, 200)
            self.assertEqual(sessions.json()["count"], 1)

            infer = client.post(
                "/api/browser-live/frame?session_id=browser_desktop_main&timestamp_ms=1234&camera_label=BrowserCam",
                content=b"fake-jpeg",
                headers={"Content-Type": "image/jpeg"},
            )
            self.assertEqual(infer.status_code, 200)
            self.assertEqual(infer.json()["session_id"], "browser_desktop_main")
