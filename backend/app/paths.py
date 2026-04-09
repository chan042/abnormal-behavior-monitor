from __future__ import annotations

from pathlib import Path
from typing import Dict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
CONFIG_ROOT = PROJECT_ROOT / "configs"
DATA_ROOT = PROJECT_ROOT / "data"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts"


def project_paths() -> Dict[str, Path]:
    return {
        "project_root": PROJECT_ROOT,
        "backend_root": BACKEND_ROOT,
        "config_root": CONFIG_ROOT,
        "data_root": DATA_ROOT,
        "artifact_root": ARTIFACT_ROOT,
        "camera_config_root": CONFIG_ROOT / "cameras",
        "roi_config_root": CONFIG_ROOT / "rois",
        "threshold_config_root": CONFIG_ROOT / "thresholds",
        "sample_data_root": DATA_ROOT / "samples",
        "model_data_root": DATA_ROOT / "models",
        "manifest_root": DATA_ROOT / "manifests",
        "event_artifact_root": ARTIFACT_ROOT / "events",
        "clip_artifact_root": ARTIFACT_ROOT / "clips",
        "snapshot_artifact_root": ARTIFACT_ROOT / "snapshots",
        "log_artifact_root": ARTIFACT_ROOT / "logs",
    }
