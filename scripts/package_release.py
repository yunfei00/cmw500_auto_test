from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path


APP_NAME = "CMW500AutoTest"
ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIST_DIR = ROOT_DIR / "dist" / APP_NAME
RELEASE_DIR = ROOT_DIR / "release"
DEVELOPMENT_VERSION = "dev"
RELEASE_VERSION_PATTERN = re.compile(
    r"^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
)
DEVELOPMENT_RUNTIME_VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-dev$"
)
REQUIRED_ARCHIVE_FILES = (
    f"{APP_NAME}/{APP_NAME}.exe",
    f"{APP_NAME}/README.md",
    f"{APP_NAME}/PROJECT_STATUS.md",
    f"{APP_NAME}/VERSION",
    f"{APP_NAME}/BUILD_INFO.json",
    f"{APP_NAME}/sample_channel_config.xlsx",
    f"{APP_NAME}/config/cmw500_lte_scpi_template.cmw500_recommended.yaml",
    f"{APP_NAME}/config/cmw500_lte_scpi_template.example.yaml",
    f"{APP_NAME}/config/cmw500_lte_scpi_template.phase8.example.yaml",
    f"{APP_NAME}/configs/lte_channel_config.xlsx",
)


def log(message: str) -> None:
    print(f"[package_release] {message}", flush=True)


def resolve_version(cli_version: str | None) -> str:
    if cli_version:
        return validate_version(cli_version)
    if os.environ.get("GITHUB_REF_TYPE", "").strip() == "tag":
        return validate_version(os.environ.get("GITHUB_REF_NAME", ""))
    return DEVELOPMENT_VERSION


def validate_version(version: str) -> str:
    normalized = version.strip()
    if normalized == DEVELOPMENT_VERSION or RELEASE_VERSION_PATTERN.fullmatch(normalized):
        return normalized
    raise ValueError(
        "Version must be 'dev' or a strict semantic release tag in vX.Y.Z format "
        "without leading zeros."
    )


def format_size(size_bytes: int) -> str:
    size_mb = size_bytes / (1024 * 1024)
    return f"{size_bytes} bytes ({size_mb:.2f} MB)"


def create_zip(version: str) -> Path:
    if not APP_DIST_DIR.is_dir():
        raise FileNotFoundError(f"Build output directory was not found: {APP_DIST_DIR}")

    filename_version = validate_version(version)
    verify_runtime_version(APP_DIST_DIR / "VERSION", filename_version)
    verify_build_info(APP_DIST_DIR / "BUILD_INFO.json", filename_version)
    if filename_version != DEVELOPMENT_VERSION:
        verify_authenticode_signature(APP_DIST_DIR / f"{APP_NAME}.exe")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = RELEASE_DIR / f"{APP_NAME}-{filename_version}-windows-x64.zip"
    manifest_path = zip_path.with_suffix(f"{zip_path.suffix}.sha256")
    if zip_path.exists():
        log(f"Removing existing package: {zip_path}")
        zip_path.unlink()
    if manifest_path.exists():
        log(f"Removing stale checksum manifest: {manifest_path}")
        manifest_path.unlink()

    log(f"Creating package: {zip_path}")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{zip_path.stem}_",
            suffix=".zip.tmp",
            dir=RELEASE_DIR,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(APP_DIST_DIR.rglob("*")):
                if not path.is_file():
                    continue
                archive_name = Path(APP_NAME) / path.relative_to(APP_DIST_DIR)
                archive.write(path, archive_name)

        verify_archive_contents(temp_path, expected_version=filename_version)
        os.replace(temp_path, zip_path)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return zip_path


def verify_runtime_version(version_path: Path, package_version: str) -> str:
    if not version_path.is_file():
        raise FileNotFoundError(f"Runtime VERSION resource was not found: {version_path}")
    runtime_version = version_path.read_text(encoding="ascii").strip()

    if package_version == DEVELOPMENT_VERSION:
        valid = bool(DEVELOPMENT_RUNTIME_VERSION_PATTERN.fullmatch(runtime_version))
    else:
        valid = runtime_version == package_version

    if not valid:
        raise RuntimeError(
            f"Runtime VERSION ({runtime_version or '<empty>'}) does not match "
            f"package version ({package_version})."
        )
    return runtime_version


def verify_authenticode_signature(executable_path: Path) -> None:
    if not executable_path.is_file():
        raise FileNotFoundError(
            f"Release executable was not found for signature verification: {executable_path}"
        )
    environment = os.environ.copy()
    environment["CMW_EXE_TO_VERIFY"] = str(executable_path.resolve())
    command = (
        "$signature = Get-AuthenticodeSignature -LiteralPath $env:CMW_EXE_TO_VERIFY; "
        "if ($signature.Status -ne 'Valid') { "
        "Write-Error ('Authenticode status: ' + $signature.Status + '; ' + "
        "$signature.StatusMessage); exit 1 }"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            "Release executable does not have a valid Authenticode signature"
            + (f": {detail}" if detail else ".")
        )
    log("Verified Authenticode signature on the release executable.")


def verify_archive_contents(zip_path: Path, expected_version: str | None = None) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        members = {name.replace("\\", "/") for name in archive.namelist()}
        if expected_version is not None:
            version_member = f"{APP_NAME}/VERSION"
            try:
                runtime_version = archive.read(version_member).decode("ascii").strip()
            except KeyError:
                runtime_version = ""
            build_info_member = f"{APP_NAME}/BUILD_INFO.json"
            try:
                build_info = json.loads(archive.read(build_info_member).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                build_info = None

    missing_files = [name for name in REQUIRED_ARCHIVE_FILES if name not in members]
    if missing_files:
        raise FileNotFoundError(
            "Release archive is missing required runtime resources: "
            + ", ".join(missing_files)
        )
    if expected_version is not None:
        if expected_version == DEVELOPMENT_VERSION:
            valid_version = bool(
                DEVELOPMENT_RUNTIME_VERSION_PATTERN.fullmatch(runtime_version)
            )
        else:
            valid_version = runtime_version == expected_version
        if not valid_version:
            raise RuntimeError(
                f"Archived VERSION ({runtime_version or '<missing>'}) does not match "
                f"package version ({expected_version})."
            )
        _validate_build_info_value(build_info, expected_version, "archive")
    log(f"Verified {len(REQUIRED_ARCHIVE_FILES)} required files in the archive.")


def verify_build_info(path: Path, package_version: str) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(f"Runtime BUILD_INFO resource was not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid runtime BUILD_INFO resource: {path}") from exc
    return _validate_build_info_value(value, package_version, str(path))


def _validate_build_info_value(
    value: object,
    package_version: str,
    source: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid BUILD_INFO in {source}.")
    version = str(value.get("version", "")).strip()
    commit = str(value.get("commit", "")).strip().lower()
    dirty = bool(value.get("dirty", False))
    if package_version == DEVELOPMENT_VERSION:
        valid_version = bool(DEVELOPMENT_RUNTIME_VERSION_PATTERN.fullmatch(version))
    else:
        valid_version = version == package_version
    if not valid_version:
        raise RuntimeError(
            f"BUILD_INFO version ({version or '<empty>'}) does not match "
            f"package version ({package_version})."
        )
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError(f"BUILD_INFO in {source} has an invalid source commit.")
    if package_version != DEVELOPMENT_VERSION and dirty:
        raise RuntimeError("Release BUILD_INFO indicates a dirty source tree.")
    if not str(value.get("built_at", "")).strip():
        raise RuntimeError(f"BUILD_INFO in {source} is missing built_at.")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_sha256_manifest(zip_path: Path) -> Path:
    manifest_path = zip_path.with_suffix(f"{zip_path.suffix}.sha256")
    digest = sha256_file(zip_path)
    manifest_path.write_text(f"{digest}  {zip_path.name}\n", encoding="ascii", newline="\n")
    return manifest_path


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
        manifest_path = create_sha256_manifest(zip_path)
        size = zip_path.stat().st_size
        log(f"Package completed: {zip_path.resolve()}")
        log(f"SHA-256 manifest: {manifest_path.resolve()}")
        log(f"Package size: {format_size(size)}")
        return 0
    except Exception as exc:
        log(f"Packaging failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
