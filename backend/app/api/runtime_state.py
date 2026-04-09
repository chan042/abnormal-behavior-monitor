from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..live.browser_service import BrowserLiveInferenceService
from ..live.service import LiveMonitorService


def merge_summary_with_camera_summaries(
    summary: Dict[str, object],
    camera_summaries: List[Dict[str, object]],
    status_source: Optional[str] = None,
) -> Dict[str, object]:
    merged = dict(summary)
    cameras = dict(summary.get("cameras", {}))
    cameras["online"] = sum(
        1 for item in camera_summaries if str(item.get("stream_status")) == "online"
    )
    cameras["total"] = len(camera_summaries)
    if status_source is not None:
        cameras["status_source"] = status_source
    merged["cameras"] = cameras
    if any(int(item.get("unreviewed_events", 0)) > 0 for item in camera_summaries) and (
        merged.get("system_state") == "stable"
    ):
        merged["system_state"] = "monitoring"
    return merged


def get_runtime_camera_summaries(
    live_monitor: Optional[LiveMonitorService] = None,
    browser_live_service: Optional[BrowserLiveInferenceService] = None,
) -> Tuple[List[Dict[str, object]], Optional[str]]:
    runtime_cameras: List[Dict[str, object]] = []
    status_sources: List[str] = []

    if live_monitor is not None:
        runtime_cameras = _merge_camera_summaries(
            runtime_cameras,
            live_monitor.get_camera_summaries(),
        )
        status_sources.append("live_monitor")
    if browser_live_service is not None:
        runtime_cameras = _merge_camera_summaries(
            runtime_cameras,
            browser_live_service.get_camera_summaries(),
        )
        status_sources.append("browser_live")

    if not status_sources:
        return ([], None)
    if len(status_sources) == 1:
        return (runtime_cameras, status_sources[0])
    return (runtime_cameras, "+".join(status_sources))


def _merge_camera_summaries(
    repository_cameras: List[Dict[str, object]],
    live_cameras: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    merged: Dict[str, Dict[str, object]] = {
        str(item["camera_id"]): dict(item) for item in repository_cameras
    }
    for live_camera in live_cameras:
        camera_id = str(live_camera["camera_id"])
        if camera_id in merged:
            merged[camera_id].update(live_camera)
        else:
            merged[camera_id] = dict(live_camera)
    return sorted(
        merged.values(),
        key=lambda item: (
            int(item.get("unreviewed_events", 0)),
            str(item.get("latest_event_started_at") or ""),
        ),
        reverse=True,
    )
