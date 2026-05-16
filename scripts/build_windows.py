from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "CMW500AutoTest"
ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT_DIR / "build"
DIST_DIR = ROOT_DIR / "dist"
APP_DIST_DIR = DIST_DIR / APP_NAME


def log(message: str) -> None:
    print(f"[build_windows] {message}", flush=True)


def warn(message: str) -> None:
    print(f"[build_windows] WARNING: {message}", flush=True)


def remove_path(path: Path) -> None:
    if path.is_dir():
        log(f"Removing directory: {path}")
        shutil.rmtree(path)
    elif path.exists():
        log(f"Removing file: {path}")
        path.unlink()


def clean_previous_builds() -> None:
    log("Cleaning previous build outputs...")
    remove_path(BUILD_DIR)
    remove_path(DIST_DIR)

    for spec_file in ROOT_DIR.glob("*.spec"):
        remove_path(spec_file)


def run_pyinstaller() -> None:
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        str(ROOT_DIR / "main.py"),
    ]

    log("Running PyInstaller...")
    log("Command: " + " ".join(command))
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def copy_required_file(source: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required resource is missing: {source}")

    destination = APP_DIST_DIR / source.name
    log(f"Copying file: {source} -> {destination}")
    shutil.copy2(source, destination)


def copy_optional_file(source: Path) -> None:
    if not source.is_file():
        warn(f"Optional resource is missing, skipped: {source}")
        return

    destination = APP_DIST_DIR / source.name
    log(f"Copying file: {source} -> {destination}")
    shutil.copy2(source, destination)


def copy_optional_directory(source: Path) -> None:
    if not source.is_dir():
        warn(f"Optional resource directory is missing, skipped: {source}")
        return

    destination = APP_DIST_DIR / source.name
    log(f"Copying directory: {source} -> {destination}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def copy_runtime_resources() -> None:
    if not APP_DIST_DIR.is_dir():
        raise FileNotFoundError(f"PyInstaller output directory was not found: {APP_DIST_DIR}")

    log("Copying runtime resources...")
    copy_required_file(ROOT_DIR / "README.md")
    copy_optional_file(ROOT_DIR / "sample_channel_config.xlsx")
    copy_optional_directory(ROOT_DIR / "config")


def main() -> int:
    try:
        log(f"Project root: {ROOT_DIR}")
        clean_previous_builds()
        run_pyinstaller()
        copy_runtime_resources()
        log(f"Build completed: {APP_DIST_DIR}")
        return 0
    except subprocess.CalledProcessError as exc:
        log(f"PyInstaller failed with exit code {exc.returncode}")
        return exc.returncode or 1
    except Exception as exc:
        log(f"Build failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
