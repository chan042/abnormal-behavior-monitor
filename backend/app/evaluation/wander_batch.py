from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from ..config import CameraConfig
from ..events.schema import EventType
from ..paths import ARTIFACT_ROOT, CONFIG_ROOT, PROJECT_ROOT
from ..pipeline import run_tracking_pipeline_for_camera
from .wander_dataset import WanderingEvaluationSegment, load_segment_manifest


@dataclass
class WanderingSegmentEvaluationResult:
    segment_id: str
    sample_id: str
    label: str
    segment_role: str
    place_id: str
    camera_id: str
    threshold_profile: str
    roi_profile_id: str
    status: str
    matched: bool
    predicted_event_count: int
    matched_event_count: int
    first_prediction_ms: Optional[int]
    first_matched_prediction_ms: Optional[int]
    detection_delay_ms: Optional[int]
    segment_duration_ms: int
    tracking_log_path: str
    event_log_path: str
    roi_config_path: str
    metadata_warnings: List[str]
    events: List[Dict[str, object]]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def score_wandering_segment(
    segment: WanderingEvaluationSegment,
    predicted_events: Iterable[Dict[str, object]],
    *,
    early_tolerance_ms: int = 10000,
    late_tolerance_ms: int = 20000,
) -> WanderingSegmentEvaluationResult:
    wandering_events = [
        payload
        for payload in predicted_events
        if str(payload.get("event_type", "")) == EventType.WANDERING_SUSPECTED.value
    ]
    prediction_timestamps = [
        int(payload["source_timestamp_ms"])
        for payload in wandering_events
        if payload.get("source_timestamp_ms") is not None
    ]
    first_prediction_ms = min(prediction_timestamps) if prediction_timestamps else None

    matched_events: List[Dict[str, object]] = []
    if segment.label == "wandering":
        window_start_ms = max(0, segment.event_start_ms - early_tolerance_ms)
        window_end_ms = segment.event_end_ms + late_tolerance_ms
        for payload in wandering_events:
            timestamp_ms = payload.get("source_timestamp_ms")
            if timestamp_ms is None:
                continue
            timestamp_ms = int(timestamp_ms)
            if window_start_ms <= timestamp_ms <= window_end_ms:
                matched_events.append(payload)
        status = "tp" if matched_events else "fn"
    else:
        matched_events = wandering_events
        status = "fp" if wandering_events else "tn"

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
            if segment.label == "wandering":
                detection_delay_ms = first_matched_ms - segment.event_start_ms

    return WanderingSegmentEvaluationResult(
        segment_id=segment.segment_id,
        sample_id=segment.sample_id,
        label=segment.label,
        segment_role=segment.segment_role,
        place_id=segment.place_id,
        camera_id=segment.camera_id,
        threshold_profile=segment.wandering_threshold_profile,
        roi_profile_id=segment.roi_profile_id,
        status=status,
        matched=bool(matched_events),
        predicted_event_count=len(wandering_events),
        matched_event_count=len(matched_events),
        first_prediction_ms=first_prediction_ms,
        first_matched_prediction_ms=first_matched_ms,
        detection_delay_ms=detection_delay_ms,
        segment_duration_ms=max(0, segment.end_ms - segment.start_ms),
        tracking_log_path="",
        event_log_path="",
        roi_config_path="",
        metadata_warnings=list(segment.metadata_warnings),
        events=wandering_events,
    )


def summarize_wandering_segment_results(
    results: Iterable[WanderingSegmentEvaluationResult],
) -> Dict[str, object]:
    result_list = list(results)
    tp = sum(1 for result in result_list if result.status == "tp")
    fn = sum(1 for result in result_list if result.status == "fn")
    fp = sum(1 for result in result_list if result.status == "fp")
    tn = sum(1 for result in result_list if result.status == "tn")

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
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

    negative_duration_ms = sum(
        max(0, result.segment_duration_ms)
        for result in result_list
        if result.label == "normal"
    )
    false_positives_per_minute = (
        round(fp / (negative_duration_ms / 60000.0), 4)
        if negative_duration_ms > 0
        else None
    )

    return {
        "segment_count": len(result_list),
        "positive_segment_count": sum(
            1 for result in result_list if result.label == "wandering"
        ),
        "negative_segment_count": sum(1 for result in result_list if result.label == "normal"),
        "tp": tp,
        "fn": fn,
        "fp": fp,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "false_positives_per_minute": false_positives_per_minute,
        "average_detection_delay_ms": average_detection_delay_ms,
        "by_place": _summarize_by_key(result_list, key="place_id"),
        "by_camera": _summarize_by_key(result_list, key="camera_id"),
        "by_profile": _summarize_by_key(result_list, key="threshold_profile"),
        "metadata_warning_count": sum(len(result.metadata_warnings) for result in result_list),
    }


def run_wandering_batch_evaluation(
    segment_manifest_path: Path,
    *,
    output_path: Path,
    roi_config_root: Path = CONFIG_ROOT / "rois" / "wandering",
    artifact_root: Optional[Path] = None,
    max_segments: Optional[int] = None,
    target_fps: int = 5,
    frame_width: int = 1280,
    frame_height: int = 720,
    model_name: str = "yolo11n.pt",
    tracker_name: str = "bytetrack.yaml",
    confidence_threshold: float = 0.25,
    wandering_threshold_path: Path = CONFIG_ROOT / "thresholds" / "wandering_wander_sample_1.yaml",
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

    results: List[WanderingSegmentEvaluationResult] = []
    for index, segment in enumerate(segments, start=1):
        segment_root = artifact_root / segment.segment_id
        logs_root = segment_root / "logs"
        events_root = segment_root / "events"
        clips_root = segment_root / "clips"
        snapshots_root = segment_root / "snapshots"
        tracking_log_path = logs_root / "tracking.jsonl"
        event_log_path = events_root / "events.jsonl"
        roi_config_path = roi_config_root / f"{segment.roi_profile_id}.yaml"

        if not roi_config_path.exists():
            raise FileNotFoundError(f"ROI config not found for {segment.roi_profile_id}: {roi_config_path}")

        camera_config = CameraConfig(
            camera_id=f"eval_{segment.sample_id}",
            name=segment.segment_id,
            source_type="file",
            source=str((PROJECT_ROOT / segment.video_path).resolve()),
            enabled=True,
            target_fps=target_fps,
            frame_width=frame_width,
            frame_height=frame_height,
            wandering_threshold_profile=segment.wandering_threshold_profile,
        )

        runner(
            camera_config=camera_config,
            output_path=tracking_log_path,
            model_name=model_name,
            tracker_name=tracker_name,
            confidence_threshold=confidence_threshold,
            enable_pose=False,
            enable_fall=False,
            enable_wandering=True,
            roi_config_path=roi_config_path,
            wandering_threshold_path=wandering_threshold_path,
            event_output_path=event_log_path,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            clip_root=clips_root,
            snapshot_root=snapshots_root,
        )

        predicted_events = _read_jsonl_objects(event_log_path)
        result = score_wandering_segment(segment, predicted_events)
        result.tracking_log_path = _project_relative(tracking_log_path)
        result.event_log_path = _project_relative(event_log_path)
        result.roi_config_path = _project_relative(roi_config_path)
        results.append(result)
        print(
            f"[{index}/{len(segments)}] {segment.segment_id}: "
            f"{result.status} ({result.predicted_event_count} predicted wandering events)"
        )

    output_payload = {
        "segment_manifest_path": _project_relative(segment_manifest_path),
        "artifact_root": _project_relative(artifact_root),
        "roi_config_root": _project_relative(roi_config_root),
        "wandering_threshold_path": _project_relative(wandering_threshold_path),
        "summary": summarize_wandering_segment_results(results),
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

def _summarize_by_key(
    results: List[WanderingSegmentEvaluationResult],
    *,
    key: str,
) -> List[Dict[str, object]]:
    grouped: Dict[str, List[WanderingSegmentEvaluationResult]] = {}
    for result in results:
        grouped.setdefault(str(getattr(result, key)), []).append(result)
    summary_rows: List[Dict[str, object]] = []
    for group_key, group_results in sorted(grouped.items()):
        summary_rows.append(
            {
                key: group_key,
                "segment_count": len(group_results),
                "tp": sum(1 for item in group_results if item.status == "tp"),
                "fn": sum(1 for item in group_results if item.status == "fn"),
                "fp": sum(1 for item in group_results if item.status == "fp"),
                "tn": sum(1 for item in group_results if item.status == "tn"),
            }
        )
    return summary_rows
