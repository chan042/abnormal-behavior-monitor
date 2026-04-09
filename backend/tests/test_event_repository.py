from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from backend.app.api.repository import EventRepository
from backend.app.events.schema import EventRecord, EventType


class EventRepositoryTest(unittest.TestCase):
    def test_list_events_returns_latest_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_root = Path(temp_dir)
            event_file = event_root / "events.jsonl"
            older = EventRecord(
                event_id="evt_old",
                camera_id="cam_01",
                track_id=1,
                event_type=EventType.WANDERING_SUSPECTED,
                started_at=datetime.fromtimestamp(1, tz=timezone.utc),
            )
            newer = EventRecord(
                event_id="evt_new",
                camera_id="cam_01",
                track_id=2,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(2, tz=timezone.utc),
            )
            event_file.write_text(
                json.dumps(older.to_dict(), ensure_ascii=True)
                + "\n"
                + json.dumps(newer.to_dict(), ensure_ascii=True)
                + "\n",
                encoding="utf-8",
            )

            repository = EventRepository(event_root)
            event_ids = [event.record.event_id for event in repository.list_events()]

            self.assertEqual(event_ids, ["evt_new", "evt_old"])

    def test_update_status_rewrites_event_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_root = Path(temp_dir)
            event_file = event_root / "events.jsonl"
            event = EventRecord(
                event_id="evt_status",
                camera_id="cam_02",
                track_id=4,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.fromtimestamp(10, tz=timezone.utc),
            )
            event_file.write_text(
                json.dumps(event.to_dict(), ensure_ascii=True) + "\n",
                encoding="utf-8",
            )

            repository = EventRepository(event_root)
            updated = repository.update_review(
                "evt_status",
                status="confirmed",
                operator_note="운영자 확인 완료",
            )

            self.assertEqual(updated.record.status, "confirmed")
            self.assertEqual(updated.record.operator_note, "운영자 확인 완료")
            self.assertIsNotNone(updated.record.reviewed_at)
            saved_payload = json.loads(event_file.read_text(encoding="utf-8").strip())
            self.assertEqual(saved_payload["status"], "confirmed")
            self.assertEqual(saved_payload["operator_note"], "운영자 확인 완료")
            self.assertIsNotNone(saved_payload["reviewed_at"])

    def test_summary_and_camera_summaries_are_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_root = Path(temp_dir)
            event_file = event_root / "events.jsonl"
            first = EventRecord(
                event_id="evt_cam01",
                camera_id="cam01",
                track_id=1,
                event_type=EventType.FALL_SUSPECTED,
                started_at=datetime.now(timezone.utc),
                status="new",
            )
            second = EventRecord(
                event_id="evt_cam02",
                camera_id="cam02",
                track_id=2,
                event_type=EventType.WANDERING_SUSPECTED,
                started_at=datetime.now(timezone.utc),
                status="confirmed",
            )
            event_file.write_text(
                "\n".join(
                    [
                        json.dumps(first.to_dict(), ensure_ascii=True),
                        json.dumps(second.to_dict(), ensure_ascii=True),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            repository = EventRepository(event_root)
            summary = repository.get_summary()
            cameras = repository.get_camera_summaries()
            analytics = repository.get_analytics()

            self.assertEqual(summary["events"]["total"], 2)
            self.assertEqual(summary["events"]["fall"], 1)
            self.assertEqual(summary["cameras"]["online"], 2)
            self.assertEqual(len(cameras), 2)
            self.assertEqual(analytics["overview"]["total_events"], 2)
            self.assertEqual(len(analytics["by_camera"]), 2)


if __name__ == "__main__":
    unittest.main()
