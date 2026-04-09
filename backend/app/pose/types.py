from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class PoseLandmarkRecord:
    index: int
    x: float
    y: float
    z: float
    visibility: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "index": self.index,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "visibility": self.visibility,
        }


@dataclass
class PoseObservation:
    frame_index: int
    timestamp_ms: int
    track_id: int
    confidence: float
    landmarks: List[PoseLandmarkRecord]

    def to_dict(self) -> Dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "timestamp_ms": self.timestamp_ms,
            "track_id": self.track_id,
            "pose_confidence": self.confidence,
            "pose_landmarks": [landmark.to_dict() for landmark in self.landmarks],
        }
