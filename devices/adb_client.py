from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from pathlib import Path


class AdbClient:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.last_error = ""

    def list_devices(self) -> list[str]:
        self.last_error = ""
        if not self._adb_available():
            return []

        success, output = self._run(["adb", "devices"])
        if not success:
            self.last_error = output
            return []

        devices: list[str] = []
        for line in output.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def install_app(self, device_id: str, apk_path: str) -> tuple[bool, str]:
        return self._run(["adb", "-s", device_id, "install", "-r", apk_path])

    def reboot(self, device_id: str) -> tuple[bool, str]:
        return self._run(["adb", "-s", device_id, "reboot"])

    def stop_app(self, device_id: str, package_name: str) -> tuple[bool, str]:
        return self._run(["adb", "-s", device_id, "shell", "am", "force-stop", package_name])

    def start_app(self, device_id: str, package_name: str) -> tuple[bool, str]:
        return self._run(
            [
                "adb",
                "-s",
                device_id,
                "shell",
                "monkey",
                "-p",
                package_name,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ]
        )

    def clear_app_data(self, device_id: str, package_name: str) -> tuple[bool, str]:
        return self._run(["adb", "-s", device_id, "shell", "pm", "clear", package_name])

    def screenshot(self, device_id: str, output_dir: str) -> tuple[bool, str]:
        if not self._adb_available():
            return False, self.last_error

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        file_path = output_path / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

        try:
            completed = subprocess.run(
                ["adb", "-s", device_id, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "ADB 命令执行超时"
        except FileNotFoundError:
            return False, self._adb_not_found_message()
        except Exception as exc:
            return False, str(exc)

        if completed.returncode != 0:
            error = completed.stderr.decode("utf-8", errors="replace").strip()
            return False, error or "截图失败"

        file_path.write_bytes(completed.stdout)
        return True, str(file_path)

    def get_current_foreground_app(self, device_id: str) -> tuple[bool, str]:
        success, output = self._run(["adb", "-s", device_id, "shell", "dumpsys", "window"])
        if not success:
            return success, output

        focus_lines = [
            line.strip()
            for line in output.splitlines()
            if "mCurrentFocus" in line or "mFocusedApp" in line
        ]
        return True, "\n".join(focus_lines) if focus_lines else output

    def _run(self, command: list[str]) -> tuple[bool, str]:
        if not self._adb_available():
            return False, self.last_error

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "ADB 命令执行超时"
        except FileNotFoundError:
            return False, self._adb_not_found_message()
        except Exception as exc:
            return False, str(exc)

        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip()
        )
        if completed.returncode != 0:
            return False, output or f"ADB 命令执行失败，返回码：{completed.returncode}"
        return True, output or "ADB 命令执行成功"

    def _adb_available(self) -> bool:
        if shutil.which("adb"):
            self.last_error = ""
            return True
        self.last_error = self._adb_not_found_message()
        return False

    def _adb_not_found_message(self) -> str:
        return "未找到 adb，请确认 Android Platform Tools 已加入 PATH"
