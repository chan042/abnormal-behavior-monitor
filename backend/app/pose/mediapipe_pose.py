from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..config import MissingDependencyError
from ..tracking.types import TrackObservation
from .types import PoseLandmarkRecord, PoseObservation


def _load_cv2():
    try:
        import cv2  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "OpenCV is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return cv2


def _load_mediapipe_pose():
    try:
        import mediapipe as mp  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "MediaPipe is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return mp


class MediaPipePoseExtractor:
    def __init__(
        self,
        model_path: Optional[Path] = None,
        model_complexity: int = 1,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        bbox_padding_ratio: float = 0.1,
    ):
        self._cv2 = _load_cv2()
        mp = _load_mediapipe_pose()
        if model_path is None:
            raise ValueError("model_path is required for MediaPipe Pose Landmarker")
        if not model_path.exists():
            raise FileNotFoundError(
                "MediaPipe Pose Landmarker model not found: %s" % model_path
            )

        base_options = mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
            delegate=mp.tasks.BaseOptions.Delegate.CPU,
        )
        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=mp.tasks.vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
            output_segmentation_masks=False,
        )
        self._mp = mp
        self._pose = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self._bbox_padding_ratio = bbox_padding_ratio
        self._model_complexity = model_complexity

    def close(self) -> None:
        self._pose.close()

    def extract_from_track(
        self,
        frame: object,
        observation: TrackObservation,
    ) -> Optional[PoseObservation]:
        frame_height, frame_width = frame.shape[:2]
        x1, y1, x2, y2 = self._expand_bbox(
            observation.x1,
            observation.y1,
            observation.x2,
            observation.y2,
            frame_width=frame_width,
            frame_height=frame_height,
        )

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        rgb_crop = self._cv2.cvtColor(crop, self._cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=rgb_crop,
        )
        result = self._pose.detect(mp_image)
        if not result.pose_landmarks:
            return None

        landmarks = self._to_landmark_records(
            result.pose_landmarks[0],
            crop_width=crop.shape[1],
            crop_height=crop.shape[0],
            offset_x=x1,
            offset_y=y1,
        )
        if not landmarks:
            return None

        visibility_scores = [landmark.visibility for landmark in landmarks]
        confidence = sum(visibility_scores) / len(visibility_scores)

        return PoseObservation(
            frame_index=observation.frame_index,
            timestamp_ms=observation.timestamp_ms,
            track_id=observation.track_id,
            confidence=confidence,
            landmarks=landmarks,
        )

    def _expand_bbox(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        frame_width: int,
        frame_height: int,
    ) -> tuple[int, int, int, int]:
        width = max(1.0, x2 - x1)
        height = max(1.0, y2 - y1)
        pad_x = width * self._bbox_padding_ratio
        pad_y = height * self._bbox_padding_ratio

        expanded_x1 = max(0, int(x1 - pad_x))
        expanded_y1 = max(0, int(y1 - pad_y))
        expanded_x2 = min(frame_width, int(x2 + pad_x))
        expanded_y2 = min(frame_height, int(y2 + pad_y))
        return expanded_x1, expanded_y1, expanded_x2, expanded_y2

    def _to_landmark_records(
        self,
        landmarks: List[object],
        crop_width: int,
        crop_height: int,
        offset_x: int,
        offset_y: int,
    ) -> List[PoseLandmarkRecord]:
        records = []
        for index, landmark in enumerate(landmarks):
            records.append(
                PoseLandmarkRecord(
                    index=index,
                    x=offset_x + (float(landmark.x) * crop_width),
                    y=offset_y + (float(landmark.y) * crop_height),
                    z=float(landmark.z),
                    visibility=float(getattr(landmark, "visibility", 0.0)),
                )
            )
        return records
