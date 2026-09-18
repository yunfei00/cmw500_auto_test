from __future__ import annotations

from typing import Any

from dut_agent.controller import DutController


def get_dut(worker: Any) -> DutController:
    dut = getattr(worker, "_android_dut_controller", None)
    if dut is None:
        dut = DutController()
        worker._android_dut_controller = dut
        worker.log_signal.emit("INFO", f"Android DUT 已连接：{dut.serial}")
    return dut


def airplane_cycle(worker: Any, hold_seconds: float = 2.0) -> None:
    dut = get_dut(worker)
    worker.log_signal.emit("INFO", f"Android DUT 飞行模式重连：ON → {hold_seconds:g}s → OFF")
    dut.airplane_cycle(hold_seconds=hold_seconds)
    worker._raise_if_stopped()


def apply_scene(worker: Any, scene: str) -> None:
    """Apply only DUT-side scenes that are currently implemented."""
    normalized = str(scene or "默认").strip()
    if normalized == "默认":
        worker.log_signal.emit("INFO", "DUT 场景：默认（不修改手机状态）")
        return
    dut = get_dut(worker)
    if normalized == "灭屏":
        worker.log_signal.emit("INFO", "DUT 场景：灭屏")
        dut.screen_off()
        return
    if normalized == "亮屏":
        worker.log_signal.emit("INFO", "DUT 场景：亮屏")
        dut.screen_on()
        dut.adb.shell("input keyevent KEYCODE_HOME")
        worker.log_signal.emit("INFO", "DUT 亮屏后已按 Home 键进入主页")
        return
    worker.log_signal.emit("WARNING", f"DUT 场景“{normalized}”暂未实现，本次不修改手机状态")
