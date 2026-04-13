# Backend Skeleton

This backend is the Python entry point for the CCTV abnormal behavior service.

Current scope:
- video ingestion
- person tracking
- pose extraction
- rule-based event detection
- event storage
- operator dashboard API layer
- FastAPI runtime for the dashboard frontend

The package intentionally starts small. Each module will be expanded as the
YOLO track and MediaPipe Pose pipeline is implemented.

Setup:
- `python3 -m venv .venv`
- `. .venv/bin/activate`
- `pip install -r backend/requirements.txt`
- `curl -L https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task -o data/models/pose_landmarker_full.task`

Run:
- `python3 -m backend.app.main paths`
- `python3 -m backend.app.main seed-demo-events`
- `python3 -m backend.app.main serve-fastapi --host 127.0.0.1 --port 8100`
- `python3 -m backend.app.main serve-fastapi --host 127.0.0.1 --port 8100 --live-camera-config configs/cameras/example_live_camera.yaml`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_camera.yaml --max-frames 50`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_rtsp_camera.yaml --max-frames 50`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_live_camera.yaml --max-frames 200 --enable-pose --enable-fall`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_camera.yaml --max-frames 50 --enable-pose`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_camera.yaml --max-frames 50 --enable-pose --enable-fall`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_camera.yaml --max-frames 50 --enable-wandering`
- `python3 -m backend.app.main track --camera-config configs/cameras/example_live_camera.yaml --enable-wandering`
- `python3 -m backend.app.main render-overlay --camera-config configs/cameras/fall_real_01.yaml --tracking-log artifacts/logs/fall_real_tracking_log_tuned.jsonl --pose-log artifacts/logs/fall_real_pose_log_tuned.jsonl --event-log artifacts/events/fall_real_events_tuned.jsonl --output artifacts/overlays/fall_real_01_overlay.mp4`
- `python3 -m backend.app.main attach-overlay-clips --overlay-video artifacts/overlays/fall_real_01_overlay.mp4 --event-log artifacts/events/fall_real_events_tuned.jsonl`
- `python3 -m backend.app.main build-swoon-manifest --dataset-root swoon_sample_1 --video-output data/manifests/swoon_videos.jsonl --segment-output data/manifests/swoon_segments.jsonl`
- `python3 -m backend.app.main build-wander-manifest --dataset-root wander_sample_1 --video-output data/manifests/wander_sample_1_videos.jsonl --segment-output data/manifests/wander_sample_1_segments.jsonl`
- `python3 -m backend.app.main evaluate-fall-manifest --segment-manifest data/manifests/swoon_segments.jsonl --output artifacts/evaluations/swoon_eval_summary.json`
- `python3 -m backend.app.main evaluate-wandering-manifest --segment-manifest data/manifests/wander_sample_1_segments.jsonl --output artifacts/evaluations/wander_eval_summary.json`
- `python3 -m backend.app.main evaluate-fall-manifest --segment-manifest data/manifests/swoon_segments.jsonl --fall-thresholds configs/thresholds/fall_swoon_candidate.yaml --output artifacts/evaluations/swoon_eval_summary_tuned.json`
- `python3 -m backend.app.main evaluate-fall-manifest --segment-manifest data/manifests/swoon_segments.jsonl --fall-thresholds configs/thresholds/fall_swoon_profiled.yaml --output artifacts/evaluations/swoon_eval_summary_profiled.json`
- `python3 -m backend.app.main build-swoon-review --segment-manifest data/manifests/swoon_segments.jsonl`
- `python3 -m backend.app.main build-wandering-review --segment-manifest data/manifests/wander_sample_1_segments.jsonl`

When events are emitted, metadata is written to `artifacts/events/` and
associated clips and snapshots are written to `artifacts/clips/<camera_id>/`
and `artifacts/snapshots/<camera_id>/`.

Demo workflow:
1. `python3 -m backend.app.main seed-demo-events`
2. `python3 -m backend.app.main serve-fastapi --host 127.0.0.1 --port 8100`
3. `cd frontend && NEXT_PUBLIC_BACKEND_ORIGIN=http://127.0.0.1:8100 npm run dev`
4. Open `http://127.0.0.1:3000`

FastAPI API:
- `GET /api/health`
- `GET /api/summary`
- `GET /api/cameras`
- `GET /api/analytics`
- `GET /api/stream`
- `GET /api/live/cameras`
- `GET /api/live/cameras/<camera_id>/frame`
- `GET /api/live/cameras/<camera_id>/stream`
- `GET /api/live/cameras/<camera_id>/status`
- `GET /api/events`
- `GET /api/events/<event_id>`
- `GET /api/events/<event_id>/clip`
- `GET /api/events/<event_id>/overlay-clip`
- `GET /api/events/<event_id>/snapshot`
- `POST /api/events/<event_id>/status`
- `GET /docs`

Current dashboard sections:
- `실시간 관제`
- `이벤트 검토`
- `통계/분석`
- `설정`

Camera status information is exposed through the dashboard and APIs, but it is
not currently a standalone top-level dashboard section.

Live overlay workflow:
1. Configure a local camera source in `configs/cameras/example_live_camera.yaml`
2. Start FastAPI with `--live-camera-config`
3. Start the Next.js frontend in `frontend/`
4. Open `실시간 관제` to view live person tracking, pose overlay, and event badges

Browser camera workflow:
1. Start the FastAPI backend
2. Start the Next.js frontend in `frontend/`
3. Open `실시간 관제`
4. Use `브라우저 카메라 라이브` to request camera permission
5. Select the Continuity Camera or local webcam
6. Click `카메라 열기`
7. The dashboard will send JPEG frames to `/api/browser-live/frame`, receive tracking and pose results, and draw overlays in the browser

Recommended development split:
1. Backend API:
   - `python3 -m backend.app.main serve-fastapi --host 127.0.0.1 --port 8100`
2. Frontend app:
   - `cd frontend`
   - `npm install`
   - `npm run dev`
3. Open `http://127.0.0.1:3000`

Notes for local webcam / Continuity Camera use:
- Set `source_type: camera`
- Set `source` to the camera device index as a string such as `"0"` or `"1"`
- On macOS, iPhone Continuity Camera should appear as a system webcam once connected

Wandering detection configuration:
- `configs/thresholds/wandering.yaml` supports `profiles:` overrides and optional fields such as `window_seconds`, `max_track_gap_seconds`, `reentry_grace_seconds`, `min_total_distance_pixels`, and `max_idle_ratio`
- `configs/thresholds/wandering_wander_sample_1.yaml` contains the initial `place-camera` profiles for `wander_sample_1`
- If `--roi-config` or `--live-roi-config` is omitted, the wandering engine automatically uses the full camera frame as the default detection region (`full_frame` ROI)
- Camera YAML may optionally set `wandering_threshold_profile`; when omitted, `camera_id` is used as the wandering profile key
- `demo_mobile` in `configs/thresholds/wandering.yaml` is intended for fixed mobile-camera demos without manual ROI setup
- ROI YAML may optionally set `axis: x|y` and `event_types: [wandering]` when wandering detection needs to be constrained to selected regions
- `configs/rois/wandering/` contains the initial evaluation-oriented ROI profiles used by the wandering evaluation CLI
- Wandering event JSON includes `details` with rule metrics such as dwell time, round trips, direction changes, and path ratio

Evaluation workflow:
1. `python3 -m backend.app.main build-swoon-manifest --dataset-root swoon_sample_1`
2. Inspect `data/manifests/swoon_videos.jsonl` and `data/manifests/swoon_segments.jsonl`
3. `python3 -m backend.app.main evaluate-fall-manifest --segment-manifest data/manifests/swoon_segments.jsonl`
4. Inspect per-segment logs under `artifacts/evaluations/` and the JSON summary output
5. For the current swoon samples, a tuned candidate threshold file is available at `configs/thresholds/fall_swoon_candidate.yaml`
6. Camera-specific override profiles can be defined in the same YAML under `profiles:` and selected with `fall_threshold_profile` in camera configs
7. For the current swoon samples, a profiled threshold file is available at `configs/thresholds/fall_swoon_profiled.yaml`
8. Build TP/FP review overlays with `python3 -m backend.app.main build-swoon-review --segment-manifest data/manifests/swoon_segments.jsonl`

Wandering dataset workflow:
1. `python3 -m backend.app.main build-wander-manifest --dataset-root wander_sample_1`
2. Inspect `data/manifests/wander_sample_1_videos.jsonl` and `data/manifests/wander_sample_1_segments.jsonl`
3. `python3 -m backend.app.main evaluate-wandering-manifest --segment-manifest data/manifests/wander_sample_1_segments.jsonl --roi-config-root configs/rois/wandering --wandering-thresholds configs/thresholds/wandering_wander_sample_1.yaml`
4. Inspect per-segment logs under `artifacts/evaluations/wander_eval_summary/` and the JSON summary output
5. Build TP/FP review overlays with `python3 -m backend.app.main build-wandering-review --segment-manifest data/manifests/wander_sample_1_segments.jsonl --evaluation-summary artifacts/evaluations/wander_eval_summary.json --evaluation-artifact-root artifacts/evaluations/wander_eval_summary`
