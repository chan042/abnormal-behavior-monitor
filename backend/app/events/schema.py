from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional


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
    status: str = "new"
    operator_note: str = ""
    reviewed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        payload["started_at"] = self.started_at.isoformat()
        payload["ended_at"] = self.ended_at.isoformat() if self.ended_at else None
        payload["reviewed_at"] = self.reviewed_at.isoformat() if self.reviewed_at else None
        return payload
