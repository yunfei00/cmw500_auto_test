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
