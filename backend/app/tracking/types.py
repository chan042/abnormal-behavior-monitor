from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class TrackObservation:
    frame_index: int
    timestamp_ms: int
    track_id: int
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "timestamp_ms": self.timestamp_ms,
            "track_id": self.track_id,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox": [self.x1, self.y1, self.x2, self.y2],
        }
