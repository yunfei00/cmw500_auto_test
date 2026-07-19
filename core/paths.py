from __future__ import annotations

import os
import sys
from pathlib import Path

from app_info import APP_ID


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT


def resource_path(relative_path: str | Path) -> Path:
    relative = Path(relative_path)
    candidates = [application_root() / relative]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / relative)
    candidates.append(PROJECT_ROOT / relative)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def user_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / APP_ID


def ensure_user_data_dir() -> Path:
    path = user_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path
