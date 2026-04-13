from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import AsyncIterator, Dict, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from ..live.browser_service import BrowserLiveInferenceService
from ..live.service import LiveMonitorService
from ..paths import ARTIFACT_ROOT
from ..scene_description.service import SceneDescriptionService
from .repository import EventRepository
from .runtime_state import (
    get_runtime_camera_summaries,
    merge_summary_with_camera_summaries,
)


class ReviewUpdatePayload(BaseModel):
    status: Optional[str] = None
    operator_note: Optional[str] = None


def create_fastapi_app(
    event_root: Optional[Path] = None,
    live_monitor: Optional[LiveMonitorService] = None,
    browser_live_service: Optional[BrowserLiveInferenceService] = None,
    scene_description_service: Optional[SceneDescriptionService] = None,
) -> FastAPI:
    repository = EventRepository(event_root or (ARTIFACT_ROOT / "events"))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if scene_description_service is not None:
            scene_description_service.start()
            for event in repository.list_events():
                if event.record.description_status == "pending":
                    scene_description_service.enqueue_event(
                        event=event.record,
                        source_path=event.source_path,
                    )
        if live_monitor is not None:
            live_monitor.start()
        try:
            yield
        finally:
            if live_monitor is not None:
                live_monitor.stop()
            if browser_live_service is not None:
                browser_live_service.reset()
            if scene_description_service is not None:
                scene_description_service.stop()

    app = FastAPI(
        title="CCTV Abnormal Behavior Monitor API",
        description="FastAPI backend for the CCTV abnormal behavior operator dashboard.",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/summary")
    async def summary() -> Dict[str, object]:
        payload = repository.get_summary()
        runtime_cameras, status_source = get_runtime_camera_summaries(
            live_monitor=live_monitor,
            browser_live_service=browser_live_service,
        )
        if runtime_cameras:
            payload = merge_summary_with_camera_summaries(
                payload,
                runtime_cameras,
                status_source=status_source,
            )
        return payload

    @app.get("/api/cameras")
    async def cameras() -> Dict[str, object]:
        runtime_cameras, _ = get_runtime_camera_summaries(
            live_monitor=live_monitor,
            browser_live_service=browser_live_service,
        )
        items = runtime_cameras or repository.get_camera_summaries()
        return {"items": items, "count": len(items)}

    @app.get("/api/analytics")
    async def analytics() -> Dict[str, object]:
        return repository.get_analytics()

    @app.get("/api/events")
    async def events() -> Dict[str, object]:
        items = [event.to_api_dict() for event in repository.list_events()]
        return {"items": items, "count": len(items)}

    @app.get("/api/events/{event_id}")
    async def event_detail(event_id: str) -> Dict[str, object]:
        stored_event = repository.get_event(event_id)
        if stored_event is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Event not found")
        return stored_event.to_api_dict()

    @app.post("/api/events/{event_id}/status")
    async def update_event_status(
        event_id: str,
        payload: ReviewUpdatePayload,
    ) -> Dict[str, object]:
        if payload.status is None and payload.operator_note is None:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="status or operator_note is required",
            )
        try:
            stored_event = repository.update_review(
                event_id=event_id,
                status=payload.status,
                operator_note=payload.operator_note,
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Event not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=str(exc),
            ) from exc
        return stored_event.to_api_dict()

    @app.get("/api/events/{event_id}/clip")
    async def event_clip(event_id: str) -> FileResponse:
        return _artifact_response(repository, event_id, "clip")

    @app.get("/api/events/{event_id}/overlay-clip")
    async def event_overlay_clip(event_id: str) -> FileResponse:
        return _artifact_response(repository, event_id, "overlay")

    @app.get("/api/events/{event_id}/snapshot")
    async def event_snapshot(event_id: str) -> FileResponse:
        return _artifact_response(repository, event_id, "snapshot")

    @app.get("/api/stream")
    async def stream(heartbeat: int = Query(default=5, ge=2, le=60)) -> StreamingResponse:
        async def event_generator() -> AsyncIterator[str]:
            previous_signature: Optional[tuple[str, int, str]] = None
            while True:
                payload = repository.get_summary()
                runtime_cameras, status_source = get_runtime_camera_summaries(
                    live_monitor=live_monitor,
                    browser_live_service=browser_live_service,
                )
                if runtime_cameras:
                    payload = merge_summary_with_camera_summaries(
                        payload,
                        runtime_cameras,
                        status_source=status_source,
                    )
                items = repository.list_events()
                latest_id = items[0].record.event_id if items else None
                latest_updated_at = repository.latest_updated_at(items)
                signature = (latest_id or "", len(items), latest_updated_at or "")
                event_name = "summary" if signature != previous_signature else "heartbeat"
                body = json.dumps(
                    {
                        "generated_at": payload["generated_at"],
                        "latest_event_id": latest_id,
                        "latest_updated_at": latest_updated_at,
                        "count": len(items),
                        "system_state": payload["system_state"],
                    },
                    ensure_ascii=False,
                )
                yield f"event: {event_name}\ndata: {body}\n\n"
                previous_signature = signature
                await asyncio.sleep(heartbeat)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.get("/api/live/cameras")
    async def live_cameras() -> Dict[str, object]:
        items = live_monitor.get_camera_summaries() if live_monitor else []
        return {"items": items, "count": len(items)}

    @app.get("/api/live/cameras/{camera_id}/frame")
    async def live_frame(camera_id: str) -> Response:
        if live_monitor is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Live camera not found")
        payload = live_monitor.get_latest_frame(camera_id)
        if payload is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Live frame not ready")
        return Response(
            content=payload,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/live/cameras/{camera_id}/status")
    async def live_camera_status(camera_id: str) -> Dict[str, object]:
        if live_monitor is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Live camera not found")
        state = live_monitor.get_state(camera_id)
        if state is None:
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Live camera not found")
        return state

    @app.get("/api/live/cameras/{camera_id}/stream")
    async def live_stream(camera_id: str) -> StreamingResponse:
        if live_monitor is None or not live_monitor.has_camera(camera_id):
            raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Live camera not found")

        async def mjpeg_generator() -> AsyncIterator[bytes]:
            boundary = b"frame"
            while True:
                payload = live_monitor.get_latest_frame(camera_id)
                if payload is not None:
                    yield (
                        b"--" + boundary + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
                        + payload
                        + b"\r\n"
                    )
                await asyncio.sleep(0.12)

        return StreamingResponse(
            mjpeg_generator(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/browser-live/sessions")
    async def browser_live_sessions() -> Dict[str, object]:
        items = (
            browser_live_service.get_session_summaries()
            if browser_live_service is not None
            else []
        )
        return {"items": items, "count": len(items)}

    @app.post("/api/browser-live/frame")
    async def browser_live_frame(
        request: Request,
        session_id: str = Query(default="browser_desktop"),
        timestamp_ms: Optional[int] = Query(default=None),
        camera_label: Optional[str] = Query(default=None),
    ) -> Dict[str, object]:
        if browser_live_service is None:
            raise HTTPException(
                status_code=HTTPStatus.NOT_FOUND,
                detail="Browser live inference is not configured",
            )
        frame_bytes = await request.body()
        try:
            return browser_live_service.infer_jpeg_frame(
                session_id=session_id,
                frame_bytes=frame_bytes,
                timestamp_ms=timestamp_ms,
                camera_label=camera_label,
            )
        except Exception as exc:  # pragma: no cover - runtime guard
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"browser live inference failed: {exc}",
            ) from exc

    return app


def _artifact_response(
    repository: EventRepository,
    event_id: str,
    kind: str,
) -> FileResponse:
    stored_event = repository.get_event(event_id)
    if stored_event is None:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Event not found")

    if kind == "clip":
        path = stored_event.clip_path
        media_type = "video/mp4"
    elif kind == "overlay":
        path = stored_event.overlay_clip_path
        media_type = "video/mp4"
    else:
        path = stored_event.snapshot_path
        media_type = "image/jpeg"

    if path is None or not path.exists():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Artifact not found")
    return FileResponse(path, media_type=media_type, filename=path.name)
