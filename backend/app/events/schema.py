from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class EventType(str, Enum):
    FALL_SUSPECTED = "fall_suspected"
    WANDERING_SUSPECTED = "wandering_suspected"


@dataclass
class EventRecord:
    event_id: str
    camera_id: str
    track_id: int
    event_type: EventType
    started_at: datetime
    ended_at: Optional[datetime] = None
    source_timestamp_ms: Optional[int] = None
    confidence: float = 0.0
    roi_id: Optional[str] = None
    clip_path: Optional[str] = None
    overlay_clip_path: Optional[str] = None
    snapshot_path: Optional[str] = None
    description: str = ""
    description_status: str = "fallback"
    description_source: str = "rule"
    description_generated_at: Optional[datetime] = None
    description_error: str = ""
    status: str = "new"
    operator_note: str = ""
    reviewed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    details: Optional[Dict[str, object]] = None

    def __post_init__(self) -> None:
        if self.updated_at is None:
            self.updated_at = (
                self.reviewed_at
                or self.description_generated_at
                or self.ended_at
                or self.started_at
            )

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        payload["started_at"] = self.started_at.isoformat()
        payload["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        payload["description_generated_at"] = (
            self.description_generated_at.isoformat()
            if self.description_generated_at
            else None
        )
        payload["reviewed_at"] = self.reviewed_at.isoformat() if self.reviewed_at else None
        payload["updated_at"] = self.updated_at.isoformat() if self.updated_at else None
        return payload


def event_record_from_dict(payload: Dict[str, Any]) -> EventRecord:
    return EventRecord(
        event_id=str(payload["event_id"]),
        camera_id=str(payload["camera_id"]),
        track_id=int(payload["track_id"]),
        event_type=EventType(str(payload["event_type"])),
        started_at=datetime.fromisoformat(str(payload["started_at"])),
        ended_at=(
            datetime.fromisoformat(str(payload["ended_at"]))
            if payload.get("ended_at")
            else None
        ),
        source_timestamp_ms=(
            int(payload["source_timestamp_ms"])
            if payload.get("source_timestamp_ms") is not None
            else None
        ),
        confidence=float(payload.get("confidence", 0.0)),
        roi_id=str(payload["roi_id"]) if payload.get("roi_id") is not None else None,
        clip_path=(
            str(payload["clip_path"]) if payload.get("clip_path") is not None else None
        ),
        overlay_clip_path=(
            str(payload["overlay_clip_path"])
            if payload.get("overlay_clip_path") is not None
            else None
        ),
        snapshot_path=(
            str(payload["snapshot_path"]) if payload.get("snapshot_path") is not None else None
        ),
        description=str(payload.get("description", "")),
        description_status=str(payload.get("description_status", "fallback")),
        description_source=str(payload.get("description_source", "rule")),
        description_generated_at=(
            datetime.fromisoformat(str(payload["description_generated_at"]))
            if payload.get("description_generated_at")
            else None
        ),
        description_error=str(payload.get("description_error", "")),
        status=str(payload.get("status", "new")),
        operator_note=str(payload.get("operator_note", "")),
        reviewed_at=(
            datetime.fromisoformat(str(payload["reviewed_at"]))
            if payload.get("reviewed_at")
            else None
        ),
        updated_at=(
            datetime.fromisoformat(str(payload["updated_at"]))
            if payload.get("updated_at")
            else None
        ),
        details=(
            dict(payload["details"])
            if isinstance(payload.get("details"), dict)
            else None
        ),
    )
