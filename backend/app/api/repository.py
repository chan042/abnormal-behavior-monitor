from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..events.schema import EventRecord, EventType, event_record_from_dict
from ..events.storage import update_event_record, utc_now
from ..paths import PROJECT_ROOT


VALID_EVENT_STATUSES = {"new", "confirmed", "false_positive", "dismissed"}
EXCLUDED_EVENT_FILE_PREFIXES = ("llm_demo_",)


@dataclass
class StoredEvent:
    record: EventRecord
    source_path: Path

    def to_api_dict(self) -> Dict[str, object]:
        payload = self.record.to_dict()
        payload["detail_url"] = f"/api/events/{self.record.event_id}"
        payload["clip_url"] = (
            f"/api/events/{self.record.event_id}/clip"
            if self.clip_path is not None and self.clip_path.exists()
            else None
        )
        payload["overlay_clip_url"] = (
            f"/api/events/{self.record.event_id}/overlay-clip"
            if self.overlay_clip_path is not None and self.overlay_clip_path.exists()
            else None
        )
        payload["snapshot_url"] = (
            f"/api/events/{self.record.event_id}/snapshot"
            if self.snapshot_path is not None and self.snapshot_path.exists()
            else None
        )
        payload["camera_name"] = _camera_metadata(self.record.camera_id)["name"]
        payload["camera_location"] = _camera_metadata(self.record.camera_id)["location"]
        payload["priority"] = _event_priority(self.record)
        return payload

    @property
    def clip_path(self) -> Optional[Path]:
        return _resolve_artifact_path(self.record.clip_path)

    @property
    def snapshot_path(self) -> Optional[Path]:
        return _resolve_artifact_path(self.record.snapshot_path)

    @property
    def overlay_clip_path(self) -> Optional[Path]:
        return _resolve_artifact_path(self.record.overlay_clip_path)


class EventRepository:
    def __init__(self, event_root: Path):
        self.event_root = event_root
        self.event_root.mkdir(parents=True, exist_ok=True)

    def list_events(self) -> List[StoredEvent]:
        events_by_id: Dict[str, StoredEvent] = {}
        for source_path in self._event_files():
            for stored_event in self._read_event_file(source_path):
                events_by_id[stored_event.record.event_id] = stored_event
        return sorted(
            events_by_id.values(),
            key=lambda item: item.record.started_at,
            reverse=True,
        )

    def get_event(self, event_id: str) -> Optional[StoredEvent]:
        for stored_event in self.list_events():
            if stored_event.record.event_id == event_id:
                return stored_event
        return None

    def update_status(self, event_id: str, status: str) -> StoredEvent:
        return self.update_review(event_id=event_id, status=status)

    def update_review(
        self,
        event_id: str,
        status: Optional[str] = None,
        operator_note: Optional[str] = None,
    ) -> StoredEvent:
        if status is not None and status not in VALID_EVENT_STATUSES:
            raise ValueError(
                "Unsupported status: {status}. Expected one of {valid}.".format(
                    status=status,
                    valid=", ".join(sorted(VALID_EVENT_STATUSES)),
                )
            )

        if status is None and operator_note is None:
            raise ValueError("At least one of status or operator_note must be provided")

        stored_event = self.get_event(event_id)
        if stored_event is None:
            raise FileNotFoundError(f"Event not found: {event_id}")

        reviewed_at = utc_now().isoformat()
        updated = update_event_record(
            stored_event.source_path,
            event_id,
            lambda payload: _apply_review_update(
                payload=payload,
                status=status,
                operator_note=operator_note,
                reviewed_at=reviewed_at,
            ),
        )
        return StoredEvent(record=updated, source_path=stored_event.source_path)

    def get_summary(self) -> Dict[str, object]:
        events = self.list_events()
        now = utc_now()
        counts_by_type = Counter(event.record.event_type.value for event in events)
        counts_by_status = Counter(event.record.status for event in events)
        camera_ids = {event.record.camera_id for event in events}
        has_new_fall = any(
            event.record.status == "new"
            and event.record.event_type == EventType.FALL_SUSPECTED
            for event in events
        )
        recent_5m = sum(
            1
            for event in events
            if now - _to_utc(event.record.started_at) <= timedelta(minutes=5)
        )
        recent_1h = sum(
            1
            for event in events
            if now - _to_utc(event.record.started_at) <= timedelta(hours=1)
        )
        latest_event = events[0].to_api_dict() if events else None
        latest_updated_at = self.latest_updated_at(events)

        if has_new_fall:
            system_state = "attention"
        elif counts_by_status.get("new", 0) > 0:
            system_state = "monitoring"
        else:
            system_state = "stable"

        return {
            "generated_at": now.isoformat(),
            "latest_updated_at": latest_updated_at,
            "system_state": system_state,
            "events": {
                "total": len(events),
                "new": counts_by_status.get("new", 0),
                "confirmed": counts_by_status.get("confirmed", 0),
                "false_positive": counts_by_status.get("false_positive", 0),
                "dismissed": counts_by_status.get("dismissed", 0),
                "fall": counts_by_type.get("fall_suspected", 0),
                "wandering": counts_by_type.get("wandering_suspected", 0),
            },
            "recent": {
                "last_5m": recent_5m,
                "last_1h": recent_1h,
            },
            "cameras": {
                "online": len(camera_ids),
                "total": len(camera_ids),
                "status_source": "event_artifacts",
            },
            "latest_event": latest_event,
        }

    def latest_updated_at(self, events: Optional[List[StoredEvent]] = None) -> Optional[str]:
        records = events if events is not None else self.list_events()
        if not records:
            return None
        latest = max(
            _to_utc(item.record.updated_at or item.record.started_at)
            for item in records
        )
        return latest.isoformat()

    def get_camera_summaries(self) -> List[Dict[str, object]]:
        grouped: Dict[str, List[StoredEvent]] = defaultdict(list)
        for event in self.list_events():
            grouped[event.record.camera_id].append(event)

        summaries: List[Dict[str, object]] = []
        for camera_id, items in grouped.items():
            items.sort(key=lambda item: item.record.started_at, reverse=True)
            latest = items[0]
            latest_payload = latest.to_api_dict()
            metadata = _camera_metadata(camera_id)
            by_type = Counter(item.record.event_type.value for item in items)
            by_status = Counter(item.record.status for item in items)

            summaries.append(
                {
                    "camera_id": camera_id,
                    "name": metadata["name"],
                    "location": metadata["location"],
                    "zone_label": metadata["zone_label"],
                    "stream_status": "online",
                    "status_source": "event_artifacts",
                    "source_type": metadata["source_type"],
                    "live_supported": False,
                    "last_seen_at": latest.record.started_at.isoformat(),
                    "total_events": len(items),
                    "unreviewed_events": by_status.get("new", 0),
                    "fall_events": by_type.get("fall_suspected", 0),
                    "wandering_events": by_type.get("wandering_suspected", 0),
                    "latest_event_id": latest.record.event_id,
                    "latest_event_type": latest.record.event_type.value,
                    "latest_event_status": latest.record.status,
                    "latest_event_started_at": latest.record.started_at.isoformat(),
                    "latest_confidence": latest.record.confidence,
                    "preview_snapshot_url": latest_payload.get("snapshot_url"),
                    "preview_clip_url": latest_payload.get("overlay_clip_url")
                    or latest_payload.get("clip_url"),
                    "detail_event_url": latest_payload.get("detail_url"),
                    "input_fps": None,
                    "inference_fps": None,
                    "processing_delay_ms": None,
                }
            )

        return sorted(
            summaries,
            key=lambda item: (
                item["unreviewed_events"],
                item["latest_event_started_at"],
            ),
            reverse=True,
        )

    def get_analytics(self) -> Dict[str, object]:
        events = self.list_events()
        counts_by_type = Counter(event.record.event_type.value for event in events)
        counts_by_status = Counter(event.record.status for event in events)
        counts_by_camera = Counter(event.record.camera_id for event in events)

        timeline: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "fall_suspected": 0, "wandering_suspected": 0}
        )
        for event in events:
            bucket = _to_utc(event.record.started_at).replace(
                minute=0, second=0, microsecond=0
            )
            bucket_key = bucket.isoformat()
            timeline[bucket_key]["total"] += 1
            timeline[bucket_key][event.record.event_type.value] += 1

        average_confidence = (
            sum(event.record.confidence for event in events) / len(events)
            if events
            else 0.0
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overview": {
                "total_events": len(events),
                "unreviewed_events": counts_by_status.get("new", 0),
                "reviewed_events": len(events) - counts_by_status.get("new", 0),
                "average_confidence": round(average_confidence, 3),
            },
            "by_type": [
                {"event_type": key, "count": value}
                for key, value in sorted(counts_by_type.items())
            ],
            "by_status": [
                {"status": key, "count": value}
                for key, value in sorted(counts_by_status.items())
            ],
            "by_camera": [
                {
                    "camera_id": camera_id,
                    "camera_name": _camera_metadata(camera_id)["name"],
                    "count": count,
                }
                for camera_id, count in sorted(
                    counts_by_camera.items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ],
            "timeline": [
                {
                    "bucket": bucket,
                    "total": values["total"],
                    "fall_suspected": values["fall_suspected"],
                    "wandering_suspected": values["wandering_suspected"],
                }
                for bucket, values in sorted(timeline.items())
            ],
            "recent_events": [event.to_api_dict() for event in events[:10]],
        }

    def _event_files(self) -> List[Path]:
        return sorted(
            path
            for path in self.event_root.glob("*.jsonl")
            if path.is_file()
            and not path.name.startswith(".")
            and not path.name.startswith(EXCLUDED_EVENT_FILE_PREFIXES)
        )

    def _read_event_file(self, source_path: Path) -> Iterable[StoredEvent]:
        with source_path.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                yield StoredEvent(
                    record=event_record_from_dict(payload),
                    source_path=source_path,
                )


def _resolve_artifact_path(raw_path: Optional[str]) -> Optional[Path]:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _apply_review_update(
    payload: Dict[str, object],
    status: Optional[str],
    operator_note: Optional[str],
    reviewed_at: str,
) -> Dict[str, object]:
    if status is not None:
        payload["status"] = status
        payload["reviewed_at"] = reviewed_at if status != "new" else None
    if operator_note is not None:
        payload["operator_note"] = operator_note
    payload["updated_at"] = utc_now().isoformat()
    return payload


def _camera_metadata(camera_id: str) -> Dict[str, str]:
    digits = "".join(char for char in camera_id if char.isdigit())[-2:] or camera_id.upper()
    return {
        "name": f"카메라 {digits}",
        "location": f"관찰 구역 {digits}",
        "zone_label": f"구역 {digits}",
        "source_type": "artifact",
    }


def _event_priority(record: EventRecord) -> str:
    if record.status == "new" and record.event_type == EventType.FALL_SUSPECTED:
        return "critical"
    if record.status == "new":
        return "warning"
    if record.status == "false_positive":
        return "muted"
    return "normal"
