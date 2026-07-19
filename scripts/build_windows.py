from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "CMW500AutoTest"
ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_DIR = ROOT_DIR / "build"
DIST_DIR = ROOT_DIR / "dist"
APP_DIST_DIR = DIST_DIR / APP_NAME
APP_EXECUTABLE = APP_DIST_DIR / f"{APP_NAME}.exe"
PYZ_ARCHIVE = BUILD_DIR / APP_NAME / "PYZ-00.pyz"
VERSION_INFO_FILE = BUILD_DIR / "windows_version_info.txt"

RELEASE_VERSION_PATTERN = re.compile(
    r"^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
)
DEVELOPMENT_VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-dev$"
)
BUILD_VERSION_ENV = "CMW_BUILD_VERSION"

REQUIRED_RUNTIME_PATHS = (
    Path(f"{APP_NAME}.exe"),
    Path("README.md"),
    Path("PROJECT_STATUS.md"),
    Path("VERSION"),
    Path("BUILD_INFO.json"),
    Path("sample_channel_config.xlsx"),
    Path("config/cmw500_lte_scpi_template.cmw500_recommended.yaml"),
    Path("config/cmw500_lte_scpi_template.example.yaml"),
    Path("config/cmw500_lte_scpi_template.phase8.example.yaml"),
    Path("configs/lte_channel_config.xlsx"),
)
REQUIRED_BUNDLED_MODULES = ("pyvisa", "pyvisa_py", "psutil")

SIGNTOOL_PATH_ENV = "CMW_SIGNTOOL_PATH"
SIGN_CERT_SHA1_ENV = "CMW_SIGN_CERT_SHA1"
SIGN_TIMESTAMP_URL_ENV = "CMW_SIGN_TIMESTAMP_URL"
REQUIRE_SIGNING_ENV = "CMW_REQUIRE_SIGNING"
DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


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

    remove_path(ROOT_DIR / f"{APP_NAME}.spec")


def run_pyinstaller() -> None:
    version_info_file = write_windows_version_info()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--hidden-import",
        "pyvisa",
        "--hidden-import",
        "pyvisa_py",
        "--version-file",
        str(version_info_file),
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


def copy_required_directory(source: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Required resource directory is missing: {source}")

    destination = APP_DIST_DIR / source.name
    log(f"Copying directory: {source} -> {destination}")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def copy_runtime_resources() -> None:
    if not APP_DIST_DIR.is_dir():
        raise FileNotFoundError(f"PyInstaller output directory was not found: {APP_DIST_DIR}")

    log("Copying runtime resources...")
    copy_required_file(ROOT_DIR / "README.md")
    copy_required_file(ROOT_DIR / "PROJECT_STATUS.md")
    copy_required_file(ROOT_DIR / "sample_channel_config.xlsx")
    copy_required_directory(ROOT_DIR / "config")
    copy_required_directory(ROOT_DIR / "configs")
    runtime_version_path = write_runtime_version()
    write_runtime_build_info()
    render_runtime_documents(runtime_version_path.read_text(encoding="ascii").strip())


def resolve_runtime_version() -> str:
    explicit_version = os.environ.get(BUILD_VERSION_ENV, "").strip()
    ref_type = os.environ.get("GITHUB_REF_TYPE", "").strip()
    ref_name = os.environ.get("GITHUB_REF_NAME", "").strip()

    if ref_type == "tag":
        if not RELEASE_VERSION_PATTERN.fullmatch(ref_name):
            raise ValueError(
                "Release tag must use strict vX.Y.Z format without leading zeros."
            )
        if explicit_version and explicit_version != ref_name:
            raise ValueError(
                f"{BUILD_VERSION_ENV} ({explicit_version}) does not match release tag ({ref_name})."
            )
        return ref_name

    if explicit_version:
        if not RELEASE_VERSION_PATTERN.fullmatch(explicit_version):
            raise ValueError(f"{BUILD_VERSION_ENV} must use strict vX.Y.Z format.")
        return explicit_version

    source_version_path = ROOT_DIR / "VERSION"
    if not source_version_path.is_file():
        raise FileNotFoundError(f"Development VERSION resource is missing: {source_version_path}")
    source_version = source_version_path.read_text(encoding="ascii").strip()
    if not DEVELOPMENT_VERSION_PATTERN.fullmatch(source_version):
        raise ValueError(
            "Development VERSION must use X.Y.Z-dev format without leading zeros."
        )
    return source_version


def write_runtime_version() -> Path:
    version = resolve_runtime_version()
    destination = APP_DIST_DIR / "VERSION"
    destination.write_text(f"{version}\n", encoding="ascii", newline="\n")
    log(f"Runtime version: {version}")
    return destination


def resolve_source_identity() -> tuple[str, bool]:
    commit = os.environ.get("GITHUB_SHA", "").strip().lower()
    if not commit:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        commit = completed.stdout.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Unable to resolve a valid 40-character source commit.")

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    dirty = bool(status.stdout.strip())
    if os.environ.get("GITHUB_REF_TYPE", "").strip() == "tag" and dirty:
        raise RuntimeError("Release-tag builds must use a clean source tree.")
    return commit, dirty


def write_runtime_build_info() -> Path:
    version = resolve_runtime_version()
    commit, dirty = resolve_source_identity()
    build_info = {
        "version": version,
        "commit": commit,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dirty": dirty,
    }
    destination = APP_DIST_DIR / "BUILD_INFO.json"
    destination.write_text(
        json.dumps(build_info, ensure_ascii=True, indent=2) + "\n",
        encoding="ascii",
        newline="\n",
    )
    log(f"Build identity: {commit[:12]}{' (dirty)' if dirty else ''}")
    return destination


def render_runtime_documents(version: str) -> None:
    source_version = (ROOT_DIR / "VERSION").read_text(encoding="ascii").strip()
    for filename in ("README.md", "PROJECT_STATUS.md"):
        path = APP_DIST_DIR / filename
        content = path.read_text(encoding="utf-8")
        content = content.replace(f"`{source_version}`", f"`{version}`")
        path.write_text(content, encoding="utf-8", newline="\n")


def write_windows_version_info() -> Path:
    version = resolve_runtime_version()
    numeric_version = version.removeprefix("v").split("-", 1)[0]
    major, minor, patch = (int(part) for part in numeric_version.split("."))
    version_tuple = f"({major}, {minor}, {patch}, 0)"
    commit, dirty = resolve_source_identity()
    VERSION_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple},
    prodvers={version_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404B0', [
        StringStruct('CompanyName', 'cmw500_tool'),
        StringStruct('FileDescription', 'CMW500 Auto Test'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', '{APP_NAME}'),
        StringStruct('OriginalFilename', '{APP_NAME}.exe'),
        StringStruct('ProductName', 'CMW500 Auto Test'),
        StringStruct('ProductVersion', '{version}'),
        StringStruct('Comments', 'Source {commit}{"; dirty tree" if dirty else ""}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    VERSION_INFO_FILE.write_text(content, encoding="utf-8", newline="\n")
    return VERSION_INFO_FILE


def verify_runtime_resources(app_dist_dir: Path | None = None) -> None:
    target_dir = app_dist_dir or APP_DIST_DIR
    missing = [
        str(path) for path in REQUIRED_RUNTIME_PATHS if not (target_dir / path).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "Release build is missing required runtime resources: " + ", ".join(missing)
        )
    log(f"Verified {len(REQUIRED_RUNTIME_PATHS)} required runtime resources.")


def verify_bundled_modules(pyz_archive: Path | None = None) -> None:
    archive_path = pyz_archive or PYZ_ARCHIVE
    if not archive_path.is_file():
        raise FileNotFoundError(f"PyInstaller module archive was not found: {archive_path}")

    from PyInstaller.archive.readers import ZlibArchiveReader

    module_names = set(ZlibArchiveReader(str(archive_path)).toc)
    missing = [name for name in REQUIRED_BUNDLED_MODULES if name not in module_names]
    if missing:
        raise RuntimeError(
            "Release build is missing required bundled Python modules: " + ", ".join(missing)
        )
    log(f"Verified {len(REQUIRED_BUNDLED_MODULES)} required bundled Python modules.")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_executable(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_file():
        return str(candidate.resolve())
    return shutil.which(value)


def sign_windows_executable() -> bool:
    """Sign the release executable when an external certificate is configured.

    The certificate must already be available in the Windows certificate store.
    No certificate material or password is stored in this repository.
    """

    signtool_value = os.environ.get(SIGNTOOL_PATH_ENV, "").strip()
    certificate_sha1 = os.environ.get(SIGN_CERT_SHA1_ENV, "").strip()
    require_signing = _env_flag(REQUIRE_SIGNING_ENV) or bool(
        RELEASE_VERSION_PATTERN.fullmatch(resolve_runtime_version())
    )

    if not signtool_value and not certificate_sha1:
        if require_signing:
            raise RuntimeError(
                f"Signing is required, but {SIGNTOOL_PATH_ENV} and {SIGN_CERT_SHA1_ENV} are not configured."
            )
        warn(
            f"Windows signing is not configured. Set {SIGNTOOL_PATH_ENV} and "
            f"{SIGN_CERT_SHA1_ENV}; set {REQUIRE_SIGNING_ENV}=1 to make signing mandatory."
        )
        return False

    if not signtool_value or not certificate_sha1:
        raise RuntimeError(
            f"Both {SIGNTOOL_PATH_ENV} and {SIGN_CERT_SHA1_ENV} must be configured for signing."
        )
    if not re.fullmatch(r"[0-9A-Fa-f]{40}", certificate_sha1):
        raise ValueError(f"{SIGN_CERT_SHA1_ENV} must be exactly 40 hexadecimal characters.")

    signtool = _resolve_executable(signtool_value)
    if not signtool:
        raise FileNotFoundError(f"signtool executable was not found: {signtool_value}")
    if not APP_EXECUTABLE.is_file():
        raise FileNotFoundError(f"Release executable was not found: {APP_EXECUTABLE}")

    command = [signtool, "sign", "/fd", "SHA256", "/sha1", certificate_sha1]
    timestamp_url = os.environ.get(SIGN_TIMESTAMP_URL_ENV, DEFAULT_TIMESTAMP_URL).strip()
    if timestamp_url:
        command.extend(["/tr", timestamp_url, "/td", "SHA256"])
    command.append(str(APP_EXECUTABLE))

    log(f"Signing executable with certificate SHA1 ending in {certificate_sha1[-8:]}...")
    subprocess.run(command, cwd=ROOT_DIR, check=True)
    subprocess.run(
        [signtool, "verify", "/pa", "/v", str(APP_EXECUTABLE)],
        cwd=ROOT_DIR,
        check=True,
    )
    log("Authenticode signature verification completed.")
    return True


def main() -> int:
    try:
        log(f"Project root: {ROOT_DIR}")
        clean_previous_builds()
        run_pyinstaller()
        copy_runtime_resources()
        verify_runtime_resources()
        verify_bundled_modules()
        sign_windows_executable()
        log(f"Build completed: {APP_DIST_DIR}")
        return 0
    except subprocess.CalledProcessError as exc:
        log(f"External build command failed with exit code {exc.returncode}")
        return exc.returncode or 1
    except Exception as exc:
        log(f"Build failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
