from __future__ import annotations

from typing import Any

from dut_agent.controller import DutController
from devices.adb_client import AdbClient, DEFAULT_SCENE_PACKAGE


# Keep the original Chinese scene names used by the LTE UI/results.
# Only app-backed scenes are translated to AutoTestSceneApp scene IDs.
APP_SCENE_MAP = {
    "音乐": "music",
    "马达": "motor",
    "前置主摄": "front_camera",
    "后置主摄": "rear_camera",
    "视频": "video",
    "游戏高负载": "game_heavy",
    "手电筒": "flashlight",
    "白屏": "white_screen",
    "动态壁纸": "dynamic_wallpaper",
    "录音": "recorder",
    "镜子": "mirror",
    "指南针": "compass",
    "环境光": "ambient_light",
}


def get_dut(worker: Any) -> DutController:
    dut = getattr(worker, "_android_dut_controller", None)
    if dut is None:
        dut = DutController()
        worker._android_dut_controller = dut
        worker.log_signal.emit("INFO", f"Android DUT 已连接：{dut.serial}")
    return dut


def get_scene_adb(worker: Any) -> AdbClient:
    client = getattr(worker, "_scene_adb_client", None)
    if client is None:
        client = AdbClient()
        worker._scene_adb_client = client
    return client


def airplane_cycle(worker: Any, hold_seconds: float = 2.0) -> None:
    dut = get_dut(worker)
    worker.log_signal.emit("INFO", f"Android DUT 飞行模式重连：ON → {hold_seconds:g}s → OFF")
    dut.airplane_cycle(hold_seconds=hold_seconds)
    worker._raise_if_stopped()


def _scene_device_id(worker: Any) -> str:
    configured = str(getattr(worker.config, "scene_device_id", "") or "").strip()
    if configured:
        return configured
    return str(get_dut(worker).serial)


def _scene_package(worker: Any) -> str:
    return str(
        getattr(worker.config, "scene_package_name", DEFAULT_SCENE_PACKAGE)
        or DEFAULT_SCENE_PACKAGE
    ).strip()


def stop_app_scene(worker: Any, *, required: bool = True) -> None:
    if not getattr(worker, "_app_scene_active", False):
        return
    client = get_scene_adb(worker)
    success, message = client.stop_scene(
        _scene_device_id(worker),
        package_name=_scene_package(worker),
    )
    if not success and required:
        raise RuntimeError(f"停止 AutoTestSceneApp 场景失败：{message}")
    worker.log_signal.emit(
        "INFO" if success else "WARNING",
        f"AutoTestSceneApp 场景停止：{message}",
    )
    worker._app_scene_active = False


def apply_scene(worker: Any, scene: str) -> None:
    """Apply one original LTE scene, extending only app-backed scene control."""
    normalized = str(scene or "默认").strip()

    # Original behavior: default means do nothing.
    if normalized == "默认":
        stop_app_scene(worker)
        worker.log_signal.emit("INFO", "DUT 场景：默认（不修改手机状态）")
        return

    # Original screen scenes stay controlled by DutController.
    if normalized == "灭屏":
        stop_app_scene(worker)
        dut = get_dut(worker)
        worker.log_signal.emit("INFO", "DUT 场景：灭屏")
        dut.screen_off()
        return

    if normalized == "亮屏":
        stop_app_scene(worker)
        dut = get_dut(worker)
        worker.log_signal.emit("INFO", "DUT 场景：亮屏")
        dut.screen_on()
        dut.home()
        worker.log_signal.emit("INFO", "DUT 亮屏后已按 Home 键进入主页")
        return

    scene_id = APP_SCENE_MAP.get(normalized)
    if scene_id is None:
        raise ValueError(f"不支持的 DUT 场景：{normalized}")

    # AutoTestSceneApp scenes are an extension of the old scene list.
    # Do not change LTE/test-mode behavior here.
    stop_app_scene(worker)
    client = get_scene_adb(worker)
    device_id = _scene_device_id(worker)
    package_name = _scene_package(worker)
    grant_ok, grant_message = client.grant_scene_permissions(device_id, package_name)
    if not grant_ok:
        worker.log_signal.emit("WARNING", f"场景权限预授权未完全成功：{grant_message}")

    success, message = client.start_scene(
        device_id,
        scene_id,
        package_name=package_name,
        duration=int(getattr(worker.config, "scene_duration", 0)),
        particles=int(getattr(worker.config, "scene_particles", 250)),
        cpu_threads=int(getattr(worker.config, "scene_cpu_threads", 2)),
        audio=bool(getattr(worker.config, "scene_audio", False)),
        vibration=bool(getattr(worker.config, "scene_vibration", False)),
    )
    if not success:
        raise RuntimeError(f"启动 DUT 场景“{normalized}”失败：{message}")
    worker._app_scene_active = True
    worker.log_signal.emit("INFO", f"DUT 场景：{normalized}（{scene_id}）")

    settle = max(0.0, float(getattr(worker.config, "scene_settle_time", 3.0)))
    if settle and not worker._interruptible_sleep(settle):
        raise RuntimeError("场景稳定等待期间测试被停止")


def cleanup_scene(worker: Any) -> None:
    """Best-effort cleanup for AutoTestSceneApp only; do not alter screen state."""
    try:
        stop_app_scene(worker, required=False)
    except Exception as exc:
        worker.log_signal.emit("WARNING", f"AutoTestSceneApp 场景清理失败：{exc}")
