from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..config import CameraConfig, load_roi_config
from ..paths import CONFIG_ROOT, PROJECT_ROOT
from ..rules.wandering import WanderingEventEngine, WanderingThresholds
from ..tracking.types import TrackObservation
from ..visualization.overlay_renderer import render_overlay_video_for_camera
from .wander_dataset import WanderingEvaluationSegment, load_segment_manifest


@dataclass
class ReviewTarget:
    review_label: str
    segment_id: str


def load_review_targets_from_evaluation(
    evaluation_summary_path: Path,
    *,
    include_tp: bool = True,
    include_fp: bool = True,
    max_segments: Optional[int] = None,
) -> List[ReviewTarget]:
    payload = json.loads(evaluation_summary_path.read_text(encoding="utf-8"))
    results = payload.get("results", [])
    targets: List[ReviewTarget] = []
    for result in results:
        status = str(result.get("status", ""))
        if status == "tp" and include_tp:
            targets.append(ReviewTarget(review_label="tp", segment_id=str(result["segment_id"])))
        if status == "fp" and include_fp:
            targets.append(ReviewTarget(review_label="fp", segment_id=str(result["segment_id"])))
    if max_segments is not None:
        targets = targets[:max_segments]
    return targets


def build_wandering_review_set(
    *,
    segment_manifest_path: Path,
    evaluation_summary_path: Path,
    threshold_path: Path,
    roi_config_root: Path = CONFIG_ROOT / "rois" / "wandering",
    evaluation_artifact_root: Path,
    output_root: Path,
    review_output_path: Path,
    include_tp: bool = True,
    include_fp: bool = True,
    max_segments: Optional[int] = None,
    target_fps: int = 5,
    frame_width: int = 1280,
    frame_height: int = 720,
) -> Dict[str, object]:
    segments = {
        segment.segment_id: segment
        for segment in load_segment_manifest(segment_manifest_path)
    }
    targets = load_review_targets_from_evaluation(
        evaluation_summary_path,
        include_tp=include_tp,
        include_fp=include_fp,
        max_segments=max_segments,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    review_output_path.parent.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, object]] = []
    for target in targets:
        segment = segments[target.segment_id]
        segment_root = evaluation_artifact_root / segment.segment_id
        tracking_log_path = segment_root / "logs" / "tracking.jsonl"
        roi_config_path = roi_config_root / f"{segment.roi_profile_id}.yaml"

        review_segment_root = output_root / target.review_label / segment.segment_id
        events_root = review_segment_root / "events"
        overlays_root = review_segment_root / "overlays"
        event_log_path = events_root / "events.jsonl"
        overlay_path = overlays_root / f"{segment.segment_id}_overlay.mp4"
        thresholds = WanderingThresholds.from_yaml(
            threshold_path,
            profile=segment.wandering_threshold_profile,
        )

        replayed_events = replay_wandering_events_for_segment(
            tracking_log_path=tracking_log_path,
            roi_config_path=roi_config_path,
            thresholds=thresholds,
        )
        _write_jsonl(replayed_events, event_log_path)

        camera_config = CameraConfig(
            camera_id=f"review_{segment.sample_id}",
            name=segment.segment_id,
            source_type="file",
            source=str((PROJECT_ROOT / segment.video_path).resolve()),
            enabled=True,
            target_fps=target_fps,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        overlay_summary = render_overlay_video_for_camera(
            camera_config=camera_config,
            tracking_log_path=tracking_log_path,
            event_log_path=event_log_path,
            output_path=overlay_path,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
        )

        records.append(
            {
                "review_label": target.review_label,
                "segment_id": segment.segment_id,
                "sample_id": segment.sample_id,
                "camera_id": segment.camera_id,
                "place_id": segment.place_id,
                "season": segment.season,
                "label": segment.label,
                "segment_role": segment.segment_role,
                "video_path": segment.video_path,
                "xml_path": segment.xml_path,
                "tracking_log_path": str(tracking_log_path),
                "event_log_path": str(event_log_path),
                "overlay_path": str(overlay_path),
                "event_count": len(replayed_events),
                "overlay_summary": overlay_summary,
            }
        )

    _write_jsonl(records, review_output_path)
    return {
        "review_output_path": str(review_output_path),
        "output_root": str(output_root),
        "targets_written": len(records),
    }


def replay_wandering_events_for_segment(
    *,
    tracking_log_path: Path,
    roi_config_path: Path,
    thresholds: WanderingThresholds,
) -> List[Dict[str, object]]:
    observations: List[TrackObservation] = []
    with tracking_log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            observations.append(
                TrackObservation(
                    frame_index=int(payload["frame_index"]),
                    timestamp_ms=int(payload["timestamp_ms"]),
                    track_id=int(payload["track_id"]),
                    class_id=int(payload["class_id"]),
                    class_name=str(payload["class_name"]),
                    confidence=float(payload["confidence"]),
                    x1=float(payload["bbox"][0]),
                    y1=float(payload["bbox"][1]),
                    x2=float(payload["bbox"][2]),
                    y2=float(payload["bbox"][3]),
                )
            )

    observations.sort(key=lambda item: (item.timestamp_ms, item.track_id))
    engine = WanderingEventEngine(
        roi_config=load_roi_config(roi_config_path),
        thresholds=thresholds,
    )
    events: List[Dict[str, object]] = []
    for observation in observations:
        events.extend(
            event.to_dict()
            for event in engine.update(
                camera_id="review",
                observation=observation,
            )
        )
    return events


def _write_jsonl(items: Iterable[Dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
