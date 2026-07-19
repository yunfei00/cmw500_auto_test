from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


APP_NAME = "CMW500 Auto Test"
APP_ID = "cmw500_auto_test"
ORGANIZATION_NAME = "cmw500_tool"

_VALID_VERSION_PATTERN = re.compile(
    r"^(?:v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)|"
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-dev)$"
)


def version_resource_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "VERSION"
    return Path(__file__).resolve().parent / "VERSION"


def build_info_resource_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "BUILD_INFO.json"
    return Path(__file__).resolve().parent / "BUILD_INFO.json"


def load_app_version(path: Path | None = None) -> str:
    version_path = path or version_resource_path()
    try:
        version = version_path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise RuntimeError(f"Required VERSION resource could not be read: {version_path}") from exc
    if not _VALID_VERSION_PATTERN.fullmatch(version):
        raise RuntimeError(f"Invalid VERSION resource: {version_path}")
    return version


APP_VERSION = load_app_version()


def load_build_info(path: Path | None = None) -> dict[str, Any]:
    build_path = path or build_info_resource_path()
    if build_path.is_file():
        try:
            value = json.loads(build_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid BUILD_INFO resource: {build_path}") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"Invalid BUILD_INFO resource: {build_path}")
        version = str(value.get("version", "")).strip()
        commit = str(value.get("commit", "")).strip().lower()
        if version != APP_VERSION:
            raise RuntimeError(
                f"BUILD_INFO version ({version or '<empty>'}) does not match VERSION ({APP_VERSION})"
            )
        if not re.fullmatch(r"[0-9a-f]{7,64}", commit):
            raise RuntimeError(f"Invalid BUILD_INFO commit: {build_path}")
        return {
            "version": version,
            "commit": commit,
            "built_at": str(value.get("built_at", "")).strip(),
            "dirty": bool(value.get("dirty", False)),
        }

    if getattr(sys, "frozen", False) or path is not None:
        raise RuntimeError(f"Required BUILD_INFO resource could not be read: {build_path}")

    project_root = Path(__file__).resolve().parent
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = completed.stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    try:
        dirty_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = bool(dirty_result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        dirty = True
    return {"version": APP_VERSION, "commit": commit, "built_at": "", "dirty": dirty}


APP_BUILD_INFO = load_build_info()
APP_BUILD_COMMIT = str(APP_BUILD_INFO["commit"])
APP_BUILD_TIME = str(APP_BUILD_INFO["built_at"])
APP_BUILD_DIRTY = bool(APP_BUILD_INFO["dirty"])
