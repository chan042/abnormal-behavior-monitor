from __future__ import annotations

import argparse
import json
from pathlib import Path

from .api.fastapi_app import create_fastapi_app
from .evaluation.batch import run_fall_batch_evaluation
from .evaluation.review import build_swoon_review_set
from .evaluation.swoon_dataset import (
    build_fall_evaluation_segments,
    parse_swoon_dataset,
    write_jsonl,
)
from .demo.seed import seed_demo_events
from .live.browser_service import BrowserLiveInferenceService
from .live.service import LiveMonitorService
from .paths import ARTIFACT_ROOT, CONFIG_ROOT, DATA_ROOT, project_paths
from .pipeline import run_tracking_pipeline
from .visualization.event_overlay_clips import attach_overlay_clips
from .visualization.overlay_renderer import render_overlay_video


def print_paths() -> None:
    print("CCTV abnormal behavior monitor skeleton")
    for name, path in project_paths().items():
        print(f"{name}: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CCTV abnormal behavior monitor backend CLI"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("paths", help="Print resolved project paths")

    fastapi_parser = subparsers.add_parser(
        "serve-fastapi",
        help="Serve the operator dashboard APIs on FastAPI",
    )
    fastapi_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind the FastAPI server",
    )
    fastapi_parser.add_argument(
        "--port",
        type=int,
        default=8100,
        help="Port for the FastAPI server",
    )
    fastapi_parser.add_argument(
        "--event-root",
        type=Path,
        default=ARTIFACT_ROOT / "events",
        help="Directory containing event JSONL files",
    )
    fastapi_parser.add_argument(
        "--live-camera-config",
        type=Path,
        action="append",
        default=[],
        help="Optional camera YAML config path to start live overlay inference",
    )
    fastapi_parser.add_argument(
        "--live-model",
        default="yolo11n.pt",
        help="YOLO model path or model name for live overlay inference",
    )
    fastapi_parser.add_argument(
        "--live-tracker",
        default="bytetrack.yaml",
        help="Tracker config for live overlay inference",
    )
    fastapi_parser.add_argument(
        "--live-conf",
        type=float,
        default=0.25,
        help="Detection confidence threshold for live overlay inference",
    )
    fastapi_parser.add_argument(
        "--live-pose-model",
        type=Path,
        default=DATA_ROOT / "models" / "pose_landmarker_full.task",
        help="MediaPipe Pose Landmarker .task model path for live overlay inference",
    )
    fastapi_parser.add_argument(
        "--live-fall-thresholds",
        type=Path,
        default=CONFIG_ROOT / "thresholds" / "fall.yaml",
        help="Fall threshold YAML used by live overlay inference",
    )
    fastapi_parser.add_argument(
        "--enable-live-wandering",
        action="store_true",
        help="Enable wandering detection in live overlay inference",
    )
    fastapi_parser.add_argument(
        "--live-roi-config",
        type=Path,
        default=CONFIG_ROOT / "rois" / "example_ward_corridor.yaml",
        help="ROI YAML used when live wandering detection is enabled",
    )
    fastapi_parser.add_argument(
        "--live-wandering-thresholds",
        type=Path,
        default=CONFIG_ROOT / "thresholds" / "wandering.yaml",
        help="Wandering threshold YAML for live overlay inference",
    )

    seed_demo_parser = subparsers.add_parser(
        "seed-demo-events",
        help="Generate synthetic event clips, snapshots, and JSONL records for dashboard demos",
    )
    seed_demo_parser.add_argument(
        "--camera-id",
        default="cam_demo_01",
        help="Camera identifier used in generated demo events",
    )
    seed_demo_parser.add_argument(
        "--event-output",
        type=Path,
        default=ARTIFACT_ROOT / "events" / "demo_events.jsonl",
        help="Output JSONL path for generated demo events",
    )
    seed_demo_parser.add_argument(
        "--clip-root",
        type=Path,
        default=ARTIFACT_ROOT / "clips",
        help="Root directory for generated demo clips",
    )
    seed_demo_parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=ARTIFACT_ROOT / "snapshots",
        help="Root directory for generated demo snapshots",
    )

    render_overlay_parser = subparsers.add_parser(
        "render-overlay",
        help="Render an overlay video from tracking, pose, and event logs",
    )
    render_overlay_parser.add_argument(
        "--camera-config",
        type=Path,
        required=True,
        help="Path to camera YAML config",
    )
    render_overlay_parser.add_argument(
        "--tracking-log",
        type=Path,
        required=True,
        help="Tracking JSONL log path",
    )
    render_overlay_parser.add_argument(
        "--pose-log",
        type=Path,
        default=None,
        help="Optional pose JSONL log path",
    )
    render_overlay_parser.add_argument(
        "--event-log",
        type=Path,
        default=None,
        help="Optional event JSONL log path",
    )
    render_overlay_parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACT_ROOT / "overlays" / "overlay.mp4",
        help="Output overlay video path",
    )
    render_overlay_parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional frame limit for development runs",
    )

    attach_overlay_parser = subparsers.add_parser(
        "attach-overlay-clips",
        help="Cut per-event overlay clips from a rendered overlay video and update event JSONL",
    )
    attach_overlay_parser.add_argument(
        "--overlay-video",
        type=Path,
        required=True,
        help="Rendered full overlay video path",
    )
    attach_overlay_parser.add_argument(
        "--event-log",
        type=Path,
        required=True,
        help="Event JSONL path to update with overlay clip paths",
    )
    attach_overlay_parser.add_argument(
        "--output-root",
        type=Path,
        default=ARTIFACT_ROOT / "overlays" / "events",
        help="Root directory for per-event overlay clips",
    )
    attach_overlay_parser.add_argument(
        "--pre-event-seconds",
        type=float,
        default=3.0,
        help="Seconds to include before the event timestamp",
    )
    attach_overlay_parser.add_argument(
        "--post-event-seconds",
        type=float,
        default=3.0,
        help="Seconds to include after the event timestamp",
    )

    swoon_manifest_parser = subparsers.add_parser(
        "build-swoon-manifest",
        help="Parse swoon XML annotations and generate video/segment manifests",
    )
    swoon_manifest_parser.add_argument(
        "--dataset-root",
        type=Path,
        required=True,
        help="Root directory containing swoon sample videos and XML files",
    )
    swoon_manifest_parser.add_argument(
        "--video-output",
        type=Path,
        default=DATA_ROOT / "manifests" / "swoon_videos.jsonl",
        help="Output JSONL path for normalized video records",
    )
    swoon_manifest_parser.add_argument(
        "--segment-output",
        type=Path,
        default=DATA_ROOT / "manifests" / "swoon_segments.jsonl",
        help="Output JSONL path for evaluation segments",
    )
    swoon_manifest_parser.add_argument(
        "--positive-pre-ms",
        type=int,
        default=5000,
        help="Milliseconds to include before falldown in positive segments",
    )
    swoon_manifest_parser.add_argument(
        "--positive-post-ms",
        type=int,
        default=8000,
        help="Milliseconds to include after falldown in positive segments",
    )
    swoon_manifest_parser.add_argument(
        "--normal-duration-ms",
        type=int,
        default=20000,
        help="Duration of generated normal pre-event segments",
    )
    swoon_manifest_parser.add_argument(
        "--normal-guard-ms",
        type=int,
        default=10000,
        help="Gap kept between the normal segment and the annotated event start",
    )

    eval_parser = subparsers.add_parser(
        "evaluate-fall-manifest",
        help="Run the rule-based fall pipeline against a segment manifest and score results",
    )
    eval_parser.add_argument(
        "--segment-manifest",
        type=Path,
        required=True,
        help="Segment manifest JSONL path created by build-swoon-manifest",
    )
    eval_parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACT_ROOT / "evaluations" / "swoon_eval_summary.json",
        help="Output JSON path for evaluation results",
    )
    eval_parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Optional root directory for per-segment logs and artifacts",
    )
    eval_parser.add_argument(
        "--max-segments",
        type=int,
        default=None,
        help="Optional segment limit for development runs",
    )
    eval_parser.add_argument(
        "--target-fps",
        type=int,
        default=5,
        help="Target FPS used when sampling evaluation segments",
    )
    eval_parser.add_argument(
        "--frame-width",
        type=int,
        default=1280,
        help="Resize width used for evaluation runs",
    )
    eval_parser.add_argument(
        "--frame-height",
        type=int,
        default=720,
        help="Resize height used for evaluation runs",
    )
    eval_parser.add_argument(
        "--model",
        default="yolo11n.pt",
        help="YOLO model path or model name for Ultralytics",
    )
    eval_parser.add_argument(
        "--tracker",
        default="bytetrack.yaml",
        help="Tracker config for Ultralytics track mode",
    )
    eval_parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Detection confidence threshold",
    )
    eval_parser.add_argument(
        "--pose-model",
        type=Path,
        default=DATA_ROOT / "models" / "pose_landmarker_full.task",
        help="MediaPipe Pose Landmarker .task model path",
    )
    eval_parser.add_argument(
        "--pose-min-detection-confidence",
        type=float,
        default=0.5,
        help="MediaPipe pose minimum detection confidence",
    )
    eval_parser.add_argument(
        "--pose-min-tracking-confidence",
        type=float,
        default=0.5,
        help="MediaPipe pose minimum tracking confidence",
    )
    eval_parser.add_argument(
        "--fall-thresholds",
        type=Path,
        default=CONFIG_ROOT / "thresholds" / "fall.yaml",
        help="Path to the fall rule threshold YAML file",
    )

    review_parser = subparsers.add_parser(
        "build-swoon-review",
        help="Build overlay review artifacts for TP/FP segments from a tuning summary",
    )
    review_parser.add_argument(
        "--segment-manifest",
        type=Path,
        required=True,
        help="Segment manifest JSONL path",
    )
    review_parser.add_argument(
        "--tuning-summary",
        type=Path,
        default=ARTIFACT_ROOT / "evaluations" / "swoon_threshold_tuning_summary.json",
        help="JSON summary comparing threshold candidates",
    )
    review_parser.add_argument(
        "--candidate-key",
        default="tuned_swoon_candidate",
        help="Candidate key inside the tuning summary JSON",
    )
    review_parser.add_argument(
        "--fall-thresholds",
        type=Path,
        default=CONFIG_ROOT / "thresholds" / "fall_swoon_candidate.yaml",
        help="Threshold YAML used to replay fall events for review overlays",
    )
    review_parser.add_argument(
        "--evaluation-artifact-root",
        type=Path,
        default=ARTIFACT_ROOT / "evaluations" / "swoon_sample_1_full_eval_baseline",
        help="Artifact root containing per-segment tracking and pose logs",
    )
    review_parser.add_argument(
        "--output-root",
        type=Path,
        default=ARTIFACT_ROOT / "review" / "swoon_candidate_review",
        help="Root directory for generated review overlays and event logs",
    )
    review_parser.add_argument(
        "--review-output",
        type=Path,
        default=ARTIFACT_ROOT / "review" / "swoon_candidate_review" / "review_manifest.jsonl",
        help="Output JSONL path describing generated review artifacts",
    )
    review_parser.add_argument(
        "--max-segments",
        type=int,
        default=None,
        help="Optional segment limit for development runs",
    )
    review_parser.add_argument(
        "--target-fps",
        type=int,
        default=5,
        help="Target FPS used when rendering review overlays",
    )
    review_parser.add_argument(
        "--frame-width",
        type=int,
        default=1280,
        help="Resize width used for review overlays",
    )
    review_parser.add_argument(
        "--frame-height",
        type=int,
        default=720,
        help="Resize height used for review overlays",
    )

    track_parser = subparsers.add_parser(
        "track", help="Run YOLO track on a configured camera source"
    )
    track_parser.add_argument(
        "--camera-config",
        type=Path,
        required=True,
        help="Path to camera YAML config",
    )
    track_parser.add_argument(
        "--output",
        type=Path,
        default=ARTIFACT_ROOT / "logs" / "tracking_log.jsonl",
        help="JSONL output path for track observations",
    )
    track_parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional frame limit for development runs",
    )
    track_parser.add_argument(
        "--model",
        default="yolo11n.pt",
        help="YOLO model path or model name for Ultralytics",
    )
    track_parser.add_argument(
        "--tracker",
        default="bytetrack.yaml",
        help="Tracker config for Ultralytics track mode",
    )
    track_parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Detection confidence threshold",
    )
    track_parser.add_argument(
        "--enable-pose",
        action="store_true",
        help="Run MediaPipe pose extraction for each tracked person",
    )
    track_parser.add_argument(
        "--enable-fall",
        action="store_true",
        help="Run the fall rule engine on top of pose observations",
    )
    track_parser.add_argument(
        "--enable-wandering",
        action="store_true",
        help="Run the wandering rule engine on tracked person motion",
    )
    track_parser.add_argument(
        "--pose-output",
        type=Path,
        default=ARTIFACT_ROOT / "logs" / "pose_log.jsonl",
        help="JSONL output path for pose observations",
    )
    track_parser.add_argument(
        "--pose-model",
        type=Path,
        default=DATA_ROOT / "models" / "pose_landmarker_full.task",
        help="MediaPipe Pose Landmarker .task model path",
    )
    track_parser.add_argument(
        "--pose-model-complexity",
        type=int,
        default=1,
        help="Reserved for future tuning. Kept for CLI compatibility.",
    )
    track_parser.add_argument(
        "--pose-min-detection-confidence",
        type=float,
        default=0.5,
        help="MediaPipe pose minimum detection confidence",
    )
    track_parser.add_argument(
        "--pose-min-tracking-confidence",
        type=float,
        default=0.5,
        help="MediaPipe pose minimum tracking confidence",
    )
    track_parser.add_argument(
        "--fall-thresholds",
        type=Path,
        default=CONFIG_ROOT / "thresholds" / "fall.yaml",
        help="Path to the fall rule threshold YAML file",
    )
    track_parser.add_argument(
        "--event-output",
        type=Path,
        default=ARTIFACT_ROOT / "events" / "events.jsonl",
        help="JSONL output path for emitted events",
    )
    track_parser.add_argument(
        "--roi-config",
        type=Path,
        default=CONFIG_ROOT / "rois" / "example_ward_corridor.yaml",
        help="Path to the ROI YAML file for wandering detection",
    )
    track_parser.add_argument(
        "--wandering-thresholds",
        type=Path,
        default=CONFIG_ROOT / "thresholds" / "wandering.yaml",
        help="Path to the wandering threshold YAML file",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "paths"):
        print_paths()
        return

    if args.command == "track":
        if args.enable_fall and not args.enable_pose:
            parser.error("--enable-fall requires --enable-pose")

        summary = run_tracking_pipeline(
            camera_config_path=args.camera_config,
            output_path=args.output,
            max_frames=args.max_frames,
            model_name=args.model,
            tracker_name=args.tracker,
            confidence_threshold=args.conf,
            enable_pose=args.enable_pose,
            enable_fall=args.enable_fall,
            enable_wandering=args.enable_wandering,
            pose_output_path=args.pose_output,
            pose_model_path=args.pose_model,
            pose_model_complexity=args.pose_model_complexity,
            pose_min_detection_confidence=args.pose_min_detection_confidence,
            pose_min_tracking_confidence=args.pose_min_tracking_confidence,
            fall_threshold_path=args.fall_thresholds,
            roi_config_path=args.roi_config,
            wandering_threshold_path=args.wandering_thresholds,
            event_output_path=args.event_output,
        )
        print("tracking_pipeline_complete")
        for key, value in summary.items():
            print(f"{key}: {value}")
        return

    if args.command == "serve-fastapi":
        live_monitor = None
        if args.live_camera_config:
            live_monitor = LiveMonitorService(
                camera_configs=args.live_camera_config,
                model_name=args.live_model,
                tracker_name=args.live_tracker,
                confidence_threshold=args.live_conf,
                enable_pose=True,
                enable_fall=True,
                enable_wandering=args.enable_live_wandering,
                pose_model_path=args.live_pose_model,
                fall_threshold_path=args.live_fall_thresholds,
                roi_config_path=args.live_roi_config,
                wandering_threshold_path=args.live_wandering_thresholds,
            )
        browser_live_service = BrowserLiveInferenceService(
            model_name=args.live_model,
            tracker_name=args.live_tracker,
            confidence_threshold=args.live_conf,
            pose_model_path=args.live_pose_model,
            fall_threshold_path=args.live_fall_thresholds,
        )
        app = create_fastapi_app(
            event_root=args.event_root,
            live_monitor=live_monitor,
            browser_live_service=browser_live_service,
        )
        import uvicorn

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return

    if args.command == "seed-demo-events":
        summary = seed_demo_events(
            camera_id=args.camera_id,
            event_output_path=args.event_output,
            clip_root=args.clip_root,
            snapshot_root=args.snapshot_root,
        )
        print("demo_events_seeded")
        for key, value in summary.items():
            print(f"{key}: {value}")
        return

    if args.command == "render-overlay":
        summary = render_overlay_video(
            camera_config_path=args.camera_config,
            tracking_log_path=args.tracking_log,
            pose_log_path=args.pose_log,
            event_log_path=args.event_log,
            output_path=args.output,
            max_frames=args.max_frames,
        )
        print("overlay_render_complete")
        for key, value in summary.items():
            print(f"{key}: {value}")
        return

    if args.command == "attach-overlay-clips":
        summary = attach_overlay_clips(
            overlay_video_path=args.overlay_video,
            event_log_path=args.event_log,
            output_root=args.output_root,
            pre_event_seconds=args.pre_event_seconds,
            post_event_seconds=args.post_event_seconds,
        )
        print("overlay_event_clips_attached")
        for key, value in summary.items():
            print(f"{key}: {value}")
        return

    if args.command == "build-swoon-manifest":
        records = parse_swoon_dataset(args.dataset_root)
        segments = build_fall_evaluation_segments(
            records,
            positive_pre_ms=args.positive_pre_ms,
            positive_post_ms=args.positive_post_ms,
            normal_duration_ms=args.normal_duration_ms,
            normal_guard_ms=args.normal_guard_ms,
        )
        video_count = write_jsonl((record.to_dict() for record in records), args.video_output)
        segment_count = write_jsonl(
            (segment.to_dict() for segment in segments), args.segment_output
        )
        print(
            json.dumps(
                {
                    "dataset_root": str(args.dataset_root),
                    "video_output": str(args.video_output),
                    "segment_output": str(args.segment_output),
                    "video_records_written": video_count,
                    "segments_written": segment_count,
                },
                ensure_ascii=True,
                indent=2,
            )
        )
        return

    if args.command == "evaluate-fall-manifest":
        summary = run_fall_batch_evaluation(
            args.segment_manifest,
            output_path=args.output,
            artifact_root=args.artifact_root,
            max_segments=args.max_segments,
            target_fps=args.target_fps,
            frame_width=args.frame_width,
            frame_height=args.frame_height,
            model_name=args.model,
            tracker_name=args.tracker,
            confidence_threshold=args.conf,
            pose_model_path=args.pose_model,
            pose_min_detection_confidence=args.pose_min_detection_confidence,
            pose_min_tracking_confidence=args.pose_min_tracking_confidence,
            fall_threshold_path=args.fall_thresholds,
        )
        print(json.dumps(summary["summary"], ensure_ascii=True, indent=2))
        return

    if args.command == "build-swoon-review":
        summary = build_swoon_review_set(
            segment_manifest_path=args.segment_manifest,
            tuning_summary_path=args.tuning_summary,
            candidate_key=args.candidate_key,
            threshold_path=args.fall_thresholds,
            evaluation_artifact_root=args.evaluation_artifact_root,
            output_root=args.output_root,
            review_output_path=args.review_output,
            max_segments=args.max_segments,
            target_fps=args.target_fps,
            frame_width=args.frame_width,
            frame_height=args.frame_height,
        )
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        return

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
