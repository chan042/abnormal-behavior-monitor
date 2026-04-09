from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


class MissingDependencyError(RuntimeError):
    """Raised when an optional runtime dependency is unavailable."""


def _load_yaml_module():
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise MissingDependencyError(
            "PyYAML is required. Install dependencies from backend/requirements.txt."
        ) from exc
    return yaml


def load_yaml_file(path: Path) -> Dict[str, Any]:
    yaml = _load_yaml_module()
    with path.open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    if not isinstance(payload, dict):
        raise ValueError("Top-level YAML structure must be a mapping")
    return payload


@dataclass
class CameraConfig:
    camera_id: str
    name: str
    source_type: str
    source: str
    enabled: bool
    target_fps: int
    frame_width: int
    frame_height: int
    fall_threshold_profile: Optional[str] = None


@dataclass
class Roi:
    roi_id: str
    name: str
    points: List[List[int]]


@dataclass
class RoiConfig:
    camera_id: str
    rois: List[Roi]


def load_camera_config(path: Path) -> CameraConfig:
    payload = load_yaml_file(path)
    return CameraConfig(
        camera_id=str(payload["camera_id"]),
        name=str(payload["name"]),
        source_type=str(payload["source_type"]),
        source=str(payload["source"]),
        enabled=bool(payload.get("enabled", True)),
        target_fps=int(payload.get("target_fps", 8)),
        frame_width=int(payload.get("frame_width", 1280)),
        frame_height=int(payload.get("frame_height", 720)),
        fall_threshold_profile=(
            str(payload["fall_threshold_profile"])
            if payload.get("fall_threshold_profile") is not None
            else None
        ),
    )


def load_roi_config(path: Path) -> RoiConfig:
    payload = load_yaml_file(path)
    rois = []
    for roi_payload in payload.get("rois", []):
        rois.append(
            Roi(
                roi_id=str(roi_payload["roi_id"]),
                name=str(roi_payload.get("name", roi_payload["roi_id"])),
                points=[[int(x), int(y)] for x, y in roi_payload["points"]],
            )
        )
    return RoiConfig(camera_id=str(payload["camera_id"]), rois=rois)
