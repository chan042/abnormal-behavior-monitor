from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from ..config import CameraConfig
from ..events.schema import EventType
from ..paths import ARTIFACT_ROOT, PROJECT_ROOT
from ..pipeline import run_tracking_pipeline_for_camera
from .swoon_dataset import EvaluationSegment, load_segment_manifest


@dataclass
class SegmentEvaluationResult:
    segment_id: str
    sample_id: str
    label: str
    segment_role: str
    status: str
    matched: bool
    predicted_event_count: int
    matched_event_count: int
    first_prediction_ms: Optional[int]
    first_matched_prediction_ms: Optional[int]
    detection_delay_ms: Optional[int]
    tracking_log_path: str
    pose_log_path: str
    event_log_path: str
    events: List[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def score_fall_segment(
    segment: EvaluationSegment,
    predicted_events: Iterable[Dict[str, object]],
    *,
    early_tolerance_ms: int = 2000,
    late_tolerance_ms: int = 8000,
) -> SegmentEvaluationResult:
    fall_events = [
        payload
        for payload in predicted_events
        if str(payload.get("event_type", "")) == EventType.FALL_SUSPECTED.value
    ]
    prediction_timestamps = [
        int(payload["source_timestamp_ms"])
        for payload in fall_events
        if payload.get("source_timestamp_ms") is not None
    ]
    first_prediction_ms = min(prediction_timestamps) if prediction_timestamps else None

    matched_events: List[Dict[str, object]] = []
    if segment.label == "fall":
        window_start_ms = segment.falldown_start_ms - early_tolerance_ms
        window_end_ms = segment.falldown_end_ms + late_tolerance_ms
        for payload in fall_events:
            timestamp_ms = payload.get("source_timestamp_ms")
            if timestamp_ms is None:
                continue
            timestamp_ms = int(timestamp_ms)
            if window_start_ms <= timestamp_ms <= window_end_ms:
                matched_events.append(payload)
        status = "tp" if matched_events else "fn"
    else:
        matched_events = fall_events
        status = "fp" if fall_events else "tn"

    first_matched_ms = None
    detection_delay_ms = None
    if matched_events:
        matched_timestamps = [
            int(payload["source_timestamp_ms"])
            for payload in matched_events
            if payload.get("source_timestamp_ms") is not None
        ]
        if matched_timestamps:
            first_matched_ms = min(matched_timestamps)
            if segment.label == "fall":
                detection_delay_ms = first_matched_ms - segment.falldown_start_ms

    return SegmentEvaluationResult(
        segment_id=segment.segment_id,
        sample_id=segment.sample_id,
        label=segment.label,
        segment_role=segment.segment_role,
        status=status,
        matched=bool(matched_events),
        predicted_event_count=len(fall_events),
        matched_event_count=len(matched_events),
        first_prediction_ms=first_prediction_ms,
        first_matched_prediction_ms=first_matched_ms,
        detection_delay_ms=detection_delay_ms,
        tracking_log_path="",
        pose_log_path="",
        event_log_path="",
        events=fall_events,
    )


def summarize_segment_results(results: Iterable[SegmentEvaluationResult]) -> Dict[str, object]:
    result_list = list(results)
    tp = sum(1 for result in result_list if result.status == "tp")
    fn = sum(1 for result in result_list if result.status == "fn")
    fp = sum(1 for result in result_list if result.status == "fp")
    tn = sum(1 for result in result_list if result.status == "tn")

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    false_positive_rate = fp / (fp + tn) if (fp + tn) else None
    detection_delays = [
        result.detection_delay_ms
        for result in result_list
        if result.detection_delay_ms is not None
    ]
    average_detection_delay_ms = (
        int(round(sum(detection_delays) / len(detection_delays)))
        if detection_delays
        else None
    )

    return {
        "segment_count": len(result_list),
        "positive_segment_count": sum(1 for result in result_list if result.label == "fall"),
        "negative_segment_count": sum(1 for result in result_list if result.label == "normal"),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "false_positive_rate": false_positive_rate,
        "average_detection_delay_ms": average_detection_delay_ms,
    }


def run_fall_batch_evaluation(
    segment_manifest_path: Path,
    *,
    output_path: Path,
    artifact_root: Optional[Path] = None,
    max_segments: Optional[int] = None,
    target_fps: int = 5,
    frame_width: int = 1280,
    frame_height: int = 720,
    model_name: str = "yolo11n.pt",
    tracker_name: str = "bytetrack.yaml",
    confidence_threshold: float = 0.25,
    pose_model_path: Optional[Path] = None,
    pose_min_detection_confidence: float = 0.5,
    pose_min_tracking_confidence: float = 0.5,
    fall_threshold_path: Optional[Path] = None,
    runner: Optional[Callable[..., Dict[str, object]]] = None,
) -> Dict[str, object]:
    if artifact_root is None:
        artifact_root = ARTIFACT_ROOT / "evaluations" / output_path.stem
    artifact_root.mkdir(parents=True, exist_ok=True)

    segments = load_segment_manifest(segment_manifest_path)
    if max_segments is not None:
        segments = segments[:max_segments]

    if runner is None:
        runner = run_tracking_pipeline_for_camera

    results: List[SegmentEvaluationResult] = []
    for index, segment in enumerate(segments, start=1):
        segment_root = artifact_root / segment.segment_id
        logs_root = segment_root / "logs"
        events_root = segment_root / "events"
        clips_root = segment_root / "clips"
        snapshots_root = segment_root / "snapshots"
        tracking_log_path = logs_root / "tracking.jsonl"
        pose_log_path = logs_root / "pose.jsonl"
        event_log_path = events_root / "events.jsonl"

        camera_config = CameraConfig(
            camera_id=f"eval_{segment.sample_id}",
            name=segment.segment_id,
            source_type="file",
            source=str((PROJECT_ROOT / segment.video_path).resolve()),
            enabled=True,
            target_fps=target_fps,
            frame_width=frame_width,
            frame_height=frame_height,
            fall_threshold_profile=segment.fall_threshold_profile,
        )

        runner(
            camera_config=camera_config,
            output_path=tracking_log_path,
            model_name=model_name,
            tracker_name=tracker_name,
            confidence_threshold=confidence_threshold,
            enable_pose=True,
            enable_fall=True,
            enable_wandering=False,
            pose_output_path=pose_log_path,
            pose_model_path=pose_model_path,
            pose_min_detection_confidence=pose_min_detection_confidence,
            pose_min_tracking_confidence=pose_min_tracking_confidence,
            fall_threshold_path=fall_threshold_path,
            event_output_path=event_log_path,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            clip_root=clips_root,
            snapshot_root=snapshots_root,
        )

        predicted_events = _read_jsonl_objects(event_log_path)
        result = score_fall_segment(segment, predicted_events)
        result.tracking_log_path = _project_relative(tracking_log_path)
        result.pose_log_path = _project_relative(pose_log_path)
        result.event_log_path = _project_relative(event_log_path)
        results.append(result)
        print(
            f"[{index}/{len(segments)}] {segment.segment_id}: "
            f"{result.status} ({result.predicted_event_count} predicted fall events)"
        )

    output_payload = {
        "segment_manifest_path": _project_relative(segment_manifest_path),
        "artifact_root": _project_relative(artifact_root),
        "summary": summarize_segment_results(results),
        "results": [result.to_dict() for result in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output_payload, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return output_payload


def _read_jsonl_objects(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    records: List[Dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _project_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())
