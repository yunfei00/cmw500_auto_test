from __future__ import annotations

import argparse
import os
import re
import zipfile
from pathlib import Path


APP_NAME = "CMW500AutoTest"
ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIST_DIR = ROOT_DIR / "dist" / APP_NAME
RELEASE_DIR = ROOT_DIR / "release"


def log(message: str) -> None:
    print(f"[package_release] {message}", flush=True)


def resolve_version(cli_version: str | None) -> str:
    return cli_version or os.environ.get("GITHUB_REF_NAME") or "dev"


def safe_filename_version(version: str) -> str:
    safe_version = re.sub(r'[<>:"/\\|?*\s]+', "-", version).strip(".-")
    return safe_version or "dev"


def format_size(size_bytes: int) -> str:
    size_mb = size_bytes / (1024 * 1024)
    return f"{size_bytes} bytes ({size_mb:.2f} MB)"


def create_zip(version: str) -> Path:
    if not APP_DIST_DIR.is_dir():
        raise FileNotFoundError(f"Build output directory was not found: {APP_DIST_DIR}")

    filename_version = safe_filename_version(version)
    if filename_version != version:
        log(f"Version contains path-unsafe characters; using '{filename_version}' for the zip filename.")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RELEASE_DIR / f"{APP_NAME}-{filename_version}-windows-x64.zip"
    if zip_path.exists():
        log(f"Removing existing package: {zip_path}")
        zip_path.unlink()

    log(f"Creating package: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(APP_DIST_DIR.rglob("*")):
            if not path.is_file():
                continue
            archive_name = Path(APP_NAME) / path.relative_to(APP_DIST_DIR)
            archive.write(path, archive_name)

    return zip_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package CMW500AutoTest Windows release zip.")
    parser.add_argument("--version", help="Release version, for example v0.1.0.")
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        version = resolve_version(args.version)
        log(f"Packaging version: {version}")
        zip_path = create_zip(version)
        size = zip_path.stat().st_size
        log(f"Package completed: {zip_path.resolve()}")
        log(f"Package size: {format_size(size)}")
        return 0
    except Exception as exc:
        log(f"Packaging failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
