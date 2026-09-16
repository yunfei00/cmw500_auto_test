from __future__ import annotations

"""LTE V1 sensitivity scan policy.

Keeps the V1 change isolated while the existing worker/UI remain stable:
- fast probe with a small packet count;
- confirm the first threshold crossing with the configured formal packet count;
- fine-search upward with the minimum step;
- verify UE connection before every probe and recover at +5 dB when detached;
- keep descending until a real BLER boundary is found (no operator stop level).
"""

import re
from typing import Any

from PySide6.QtWidgets import QSpinBox

from core.test_worker import TestWorker
from ui.left_panel import LeftPanel


FAST_PACKET_DEFAULT = 100
START_LEVEL_DEFAULT = -85.0
MAX_STEP_DEFAULT = 0.3
MIN_STEP_DEFAULT = 0.1
BLER_THRESHOLD_DEFAULT = 5.0
RECONNECT_BOOST_DB = 5.0
RECONNECT_ATTEMPTS = 3
FULL_CELL_BW_POWER_QUERY = "SENSe:LTE:SIGN:DL:PCC:FCPOWer?"


_original_create_lte_instrument_group = LeftPanel._create_lte_instrument_group
_original_collect_lte_config = LeftPanel.collect_lte_config
_original_measure_level = TestWorker._measure_level


def _create_lte_instrument_group(self: LeftPanel):
    group = _original_create_lte_instrument_group(self)
    self.sensitivity_upper_spin.setValue(START_LEVEL_DEFAULT)
    self.start_level_spin.setValue(START_LEVEL_DEFAULT)

    # Keep the legacy field only so the current LteTestConfig constructor stays
    # backward compatible. It is hidden from operators and ignored by scanning.
    self.stop_level_spin.setVisible(False)
    form = group.layout()
    if hasattr(form, "labelForField"):
        stop_label = form.labelForField(self.stop_level_spin)
        if stop_label is not None:
            stop_label.setVisible(False)

    self.packet_count_spin.setValue(1000)
    self.max_step_spin.setValue(MAX_STEP_DEFAULT)
    self.min_step_spin.setValue(MIN_STEP_DEFAULT)
    self.bler_threshold_spin.setValue(BLER_THRESHOLD_DEFAULT)

    self.fast_packet_count_spin = QSpinBox()
    self.fast_packet_count_spin.setRange(1, 999999)
    self.fast_packet_count_spin.setValue(FAST_PACKET_DEFAULT)
    if hasattr(form, "insertRow"):
        row = max(0, form.rowCount() - 6)
        form.insertRow(row, "快速测试包个数：", self.fast_packet_count_spin)
    else:
        form.addRow("快速测试包个数：", self.fast_packet_count_spin)
    return group


def _collect_lte_config(self: LeftPanel):
    config = _original_collect_lte_config(self)
    config.fast_packet_count = int(self.fast_packet_count_spin.value())
    config.reconnect_boost_db = RECONNECT_BOOST_DB
    config.reconnect_attempts = RECONNECT_ATTEMPTS
    return config


def _wait_connected(worker: TestWorker, timeout: float) -> bool:
    method = getattr(worker.instrument, "wait_for_attach", None)
    if not callable(method):
        return True
    result = worker._call_with_supported_kwargs(
        method,
        timeout=timeout,
        cancel_check=worker._is_stopped,
    )
    worker._raise_if_stopped()
    worker._emit_instrument_warning()
    return bool(result)


def _ensure_connected_for_probe(
    worker: TestWorker,
    item: Any,
    requested_level: float,
) -> tuple[float, bool]:
    """Set requested point, verify attach, and recover upward if detached."""

    level = float(requested_level)
    instrument_level = worker._instrument_level_for_dut(item, level)
    worker.instrument.set_rx_level(instrument_level)
    worker._raise_if_stopped()
    worker._emit_instrument_warning()

    if _wait_connected(worker, 0.0):
        return level, False

    boost = float(getattr(worker.config, "reconnect_boost_db", RECONNECT_BOOST_DB))
    attempts = int(getattr(worker.config, "reconnect_attempts", RECONNECT_ATTEMPTS))
    worker.log_signal.emit(
        "WARNING",
        f"{item.band}/{item.channel} DUT={level:g} dBm UE 已掉线，开始 +{boost:g} dB 恢复",
    )

    recovery_level = level
    for attempt in range(1, attempts + 1):
        recovery_level = round(recovery_level + boost, 10)
        recovery_instrument_level = worker._instrument_level_for_dut(item, recovery_level)
        worker.instrument.set_rx_level(recovery_instrument_level)
        worker._raise_if_stopped()
        worker._emit_instrument_warning()
        worker.log_signal.emit(
            "INFO", f"UE 重连 {attempt}/{attempts}：DUT={recovery_level:g} dBm"
        )
        if _wait_connected(worker, 10.0):
            worker.log_signal.emit(
                "INFO",
                f"UE 已恢复连接，从 {recovery_level:g} dBm 重新搜索灵敏度",
            )
            return recovery_level, True

    raise RuntimeError(
        f"UE 掉线后连续 {attempts} 次 +{boost:g} dB 仍无法恢复连接"
    )


def _query_full_cell_bw_power(worker: TestWorker) -> float | None:
    """Read the CMW500 Full Cell BW Power for the current LTE DL level."""

    if bool(getattr(worker.instrument, "is_simulation", False)):
        return None
    query = getattr(worker.instrument, "query", None)
    if not callable(query):
        return None
    try:
        response = str(query(FULL_CELL_BW_POWER_QUERY)).strip()
        match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?", response)
        if not match:
            raise ValueError(f"无法解析仪表返回值：{response!r}")
        return float(match.group(0))
    except Exception as exc:
        worker.log_signal.emit("WARNING", f"Full Cell BW Power 查询失败：{exc}")
        return None


def _measure_with_packets(
    worker: TestWorker,
    item: Any,
    level: float,
    phase: str,
    current: int,
    total: int,
    packet_count: int,
) -> bool:
    """Use existing measurement/report path with a phase-specific packet count."""

    original_packets = worker.config.packet_count
    original_retries = worker.config.retry_count
    worker.config.packet_count = int(packet_count)
    worker.config.retry_count = 0
    try:
        passed = _original_measure_level(worker, item, level, phase, current, total)
        full_cell_bw_power = _query_full_cell_bw_power(worker)
        if full_cell_bw_power is not None:
            instrument_level = worker._instrument_level_for_dut(item, level)
            worker.log_signal.emit(
                "INFO",
                f"{phase} {item.band}/{item.channel} CMW RS EPRE={instrument_level:g} dBm, "
                f"Full Cell BW Power={full_cell_bw_power:g} dBm",
            )
        return passed
    finally:
        worker.config.packet_count = original_packets
        worker.config.retry_count = original_retries


def _scan_item(self: TestWorker, item: Any, current: int, total: int) -> None:
    level = float(self.config.start_level)
    fast_packets = int(getattr(self.config, "fast_packet_count", FAST_PACKET_DEFAULT))
    formal_packets = int(self.config.packet_count)
    max_step = float(self.config.max_step)
    min_step = float(self.config.min_step)

    self.log_signal.emit(
        "INFO",
        f"LTE 快速灵敏度扫描：起点={level:g} dBm，快速={fast_packets}包/{max_step:g}dB，"
        f"确认={formal_packets}包，细扫={min_step:g}dB，门限={self.config.bler_threshold:g}%",
    )

    while True:
        # No arbitrary stop level: descend until BLER finds the boundary. UE
        # detach and instrument range errors remain explicit recovery/error paths.
        level, recovered = _ensure_connected_for_probe(self, item, level)
        if recovered and level > float(self.config.start_level):
            self.log_signal.emit(
                "WARNING",
                f"恢复电平 {level:g} dBm 高于初始电平 {self.config.start_level:g} dBm",
            )

        passed = _measure_with_packets(
            self, item, level, "FAST", current, total, fast_packets
        )
        if passed:
            level = round(level - max_step, 10)
            continue

        confirm_level, recovered = _ensure_connected_for_probe(self, item, level)
        if recovered:
            level = confirm_level
            continue
        confirmed_pass = _measure_with_packets(
            self, item, level, "CONFIRM", current, total, formal_packets
        )
        if confirmed_pass:
            level = round(level - max_step, 10)
            continue

        confirmed_fail_level = level
        self.log_signal.emit(
            "INFO",
            f"确认 FAIL：{confirmed_fail_level:g} dBm，开始 {min_step:g} dB 向上细扫",
        )

        fine_level = round(confirmed_fail_level + min_step, 10)
        while True:
            fine_level, recovered = _ensure_connected_for_probe(self, item, fine_level)
            if recovered:
                level = fine_level
                self.log_signal.emit(
                    "INFO",
                    f"细扫期间发生掉线，已恢复到 {level:g} dBm，重新进入快速搜索",
                )
                break
            if _measure_with_packets(
                self, item, fine_level, "FINE", current, total, formal_packets
            ):
                self.log_signal.emit(
                    "INFO",
                    f"Sensitivity 边界：PASS={fine_level:g} dBm，"
                    f"FAIL={confirmed_fail_level:g} dBm",
                )
                return
            confirmed_fail_level = fine_level
            fine_level = round(fine_level + min_step, 10)


def apply_lte_fast_scan_policy() -> None:
    """Install the V1 LTE scan policy once at application startup."""

    if getattr(LeftPanel, "_lte_fast_scan_policy_applied", False):
        return
    LeftPanel._create_lte_instrument_group = _create_lte_instrument_group
    LeftPanel.collect_lte_config = _collect_lte_config
    TestWorker._scan_item = _scan_item
    LeftPanel._lte_fast_scan_policy_applied = True
