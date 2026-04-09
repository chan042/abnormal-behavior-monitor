from __future__ import annotations

from typing import List

from ..config import MissingDependencyError
from .types import TrackObservation


def _load_yolo():
    try:
        from ultralytics import YOLO  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "Ultralytics is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return YOLO


class YoloPersonTracker:
    def __init__(
        self,
        model_name: str = "yolo11n.pt",
        tracker_name: str = "bytetrack.yaml",
        confidence_threshold: float = 0.25,
    ):
        yolo_cls = _load_yolo()
        self.model = yolo_cls(model_name)
        self.tracker_name = tracker_name
        self.confidence_threshold = confidence_threshold

    def track_frame(
        self,
        frame: object,
        frame_index: int,
        timestamp_ms: int,
    ) -> List[TrackObservation]:
        results = self.model.track(
            source=frame,
            persist=True,
            tracker=self.tracker_name,
            conf=self.confidence_threshold,
            classes=[0],
            verbose=False,
        )

        if not results:
            return []

        result = results[0]
        boxes = result.boxes
        if boxes is None or boxes.xyxy is None:
            return []

        track_ids = boxes.id.tolist() if boxes.id is not None else []
        confidences = boxes.conf.tolist() if boxes.conf is not None else []
        class_ids = boxes.cls.tolist() if boxes.cls is not None else []
        xyxy_values = boxes.xyxy.tolist()

        observations = []
        names = getattr(result, "names", {}) or {}
        for index, coords in enumerate(xyxy_values):
            if index >= len(track_ids):
                continue

            class_id = int(class_ids[index]) if index < len(class_ids) else 0
            observations.append(
                TrackObservation(
                    frame_index=frame_index,
                    timestamp_ms=timestamp_ms,
                    track_id=int(track_ids[index]),
                    class_id=class_id,
                    class_name=str(names.get(class_id, "person")),
                    confidence=float(confidences[index]) if index < len(confidences) else 0.0,
                    x1=float(coords[0]),
                    y1=float(coords[1]),
                    x2=float(coords[2]),
                    y2=float(coords[3]),
                )
            )
        return observations
