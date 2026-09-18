from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path


DEFAULT_SCENE_PACKAGE = "com.yunfei.autotestscene"
SCENE_ENTRY_ACTIVITY = ".SceneEntryActivity"
SCENE_STOP_ACTION = "com.yunfei.autotestscene.STOP"

SCENE_ACTIVITY_MAP = {
    "motor": "MotorSceneActivity",
    "music": "MusicSceneActivity",
    "video": "VideoSceneActivity",
    "dynamic_wallpaper": "DynamicWallpaperSceneActivity",
    "game_heavy": "GameHeavySceneActivity",
    "flashlight": "FlashlightSceneActivity",
    "recorder": "RecorderSceneActivity",
    "mirror": "MirrorSceneActivity",
    "compass": "CompassSceneActivity",
    "ambient_light": "AmbientLightSceneActivity",
    "white_screen": "WhiteScreenSceneActivity",
    "front_camera": "FrontCameraSceneActivity",
    "rear_camera": "RearCameraSceneActivity",
}


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
        return self._run(["adb", "-s", device_id, "install", "-r", "-g", apk_path])

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

    def grant_scene_permissions(
        self,
        device_id: str,
        package_name: str = DEFAULT_SCENE_PACKAGE,
    ) -> tuple[bool, str]:
        permissions = [
            "android.permission.CAMERA",
            "android.permission.RECORD_AUDIO",
        ]
        messages: list[str] = []
        for permission in permissions:
            success, output = self._run(
                ["adb", "-s", device_id, "shell", "pm", "grant", package_name, permission]
            )
            if not success:
                return False, f"{permission}: {output}"
            messages.append(f"{permission}: OK")
        return True, "; ".join(messages)

    def start_scene(
        self,
        device_id: str,
        scene_id: str,
        *,
        package_name: str = DEFAULT_SCENE_PACKAGE,
        duration: int = 0,
        style: str | None = None,
        particles: int = 250,
        cpu_threads: int = 2,
        audio: bool = False,
        vibration: bool = False,
        verify_timeout: float = 10.0,
    ) -> tuple[bool, str]:
        scene_id = str(scene_id).strip().lower()
        if scene_id == "idle":
            return self.stop_scene(device_id, package_name=package_name)

        if scene_id not in SCENE_ACTIVITY_MAP:
            return False, f"不支持的场景：{scene_id}"

        self.stop_scene(device_id, package_name=package_name, verify=False)
        command = [
            "adb",
            "-s",
            device_id,
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            f"{package_name}/{SCENE_ENTRY_ACTIVITY}",
            "--es",
            "scene",
            scene_id,
            "--ei",
            "duration",
            str(max(0, int(duration))),
            "--ei",
            "particles",
            str(max(20, int(particles))),
            "--ei",
            "cpu_threads",
            str(max(0, int(cpu_threads))),
            "--ez",
            "audio",
            "true" if audio else "false",
            "--ez",
            "vibration",
            "true" if vibration else "false",
        ]
        if style:
            command.extend(["--es", "style", style])

        success, output = self._run(command)
        if not success:
            return False, output

        verified, status = self.wait_for_scene(
            device_id,
            scene_id,
            package_name=package_name,
            timeout=verify_timeout,
        )
        if not verified:
            return False, f"场景启动命令成功，但未确认进入 {scene_id}：{status}"
        return True, f"{scene_id} RUNNING"

    def stop_scene(
        self,
        device_id: str,
        *,
        package_name: str = DEFAULT_SCENE_PACKAGE,
        verify: bool = True,
        verify_timeout: float = 5.0,
    ) -> tuple[bool, str]:
        success, output = self._run(
            [
                "adb",
                "-s",
                device_id,
                "shell",
                "am",
                "broadcast",
                "-a",
                SCENE_STOP_ACTION,
                "-p",
                package_name,
            ]
        )
        if not success:
            return False, output
        if not verify:
            return True, output

        deadline = time.monotonic() + max(0.2, float(verify_timeout))
        last_status = ""
        while time.monotonic() < deadline:
            status_ok, scene_id = self.get_scene_status(device_id, package_name=package_name)
            if not status_ok:
                last_status = scene_id
                time.sleep(0.2)
                continue
            if scene_id == "idle":
                return True, "scene STOPPED"
            last_status = scene_id
            time.sleep(0.2)

        force_ok, force_output = self.stop_app(device_id, package_name)
        if force_ok:
            return True, f"STOP 广播后场景仍为 {last_status or 'unknown'}，已 force-stop"
        return False, f"场景停止确认失败：{last_status}; force-stop: {force_output}"

    def get_scene_status(
        self,
        device_id: str,
        *,
        package_name: str = DEFAULT_SCENE_PACKAGE,
    ) -> tuple[bool, str]:
        success, output = self._run(
            ["adb", "-s", device_id, "shell", "dumpsys", "activity", "activities"]
        )
        if not success:
            return False, output

        relevant_lines = [
            line.strip()
            for line in output.splitlines()
            if package_name in line and ("mResumedActivity" in line or "topResumedActivity" in line)
        ]
        if not relevant_lines:
            return True, "idle"

        joined = "\n".join(relevant_lines)
        for scene_id, activity_name in SCENE_ACTIVITY_MAP.items():
            if activity_name in joined:
                return True, scene_id
        return True, "idle"

    def wait_for_scene(
        self,
        device_id: str,
        scene_id: str,
        *,
        package_name: str = DEFAULT_SCENE_PACKAGE,
        timeout: float = 10.0,
    ) -> tuple[bool, str]:
        deadline = time.monotonic() + max(0.2, float(timeout))
        last_status = "unknown"
        while time.monotonic() < deadline:
            success, status = self.get_scene_status(device_id, package_name=package_name)
            if not success:
                last_status = status
            else:
                last_status = status
                if status == scene_id:
                    return True, status
            time.sleep(0.2)
        return False, last_status

    def screenshot(self, device_id: str, output_dir: str) -> tuple[bool, str]:
        if not self._adb_available():
            return False, self.last_error

        output_path = Path(output_dir)
        try:
            output_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"截图目录创建失败：{exc}"
        file_path = output_path / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"

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

        if not completed.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, "ADB 返回的截图不是有效 PNG 数据"
        try:
            file_path.write_bytes(completed.stdout)
        except OSError as exc:
            return False, f"截图保存失败：{exc}"
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
