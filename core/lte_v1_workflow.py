from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import Any

from core.result_judge import judge_bler
from core.test_worker import TestWorker, _StopRequested
from devices.cmw500_controller import RealCMW500
from ui.left_panel import LeftPanel


_COM_ROUTES: dict[int, tuple[str, str, str, str]] = {
    1: ("RF1C", "RX1", "RF1C", "TX1"),
    2: ("RF2C", "RX1", "RF2C", "TX1"),
    3: ("RF3C", "RX2", "RF3C", "TX2"),
    4: ("RF4C", "RX2", "RF4C", "TX2"),
}

_TDD_BANDS = set(range(33, 54))
_PATCHED = False


def _normalize_csv(value: str) -> str:
    return ",".join(
        part.strip().strip('"').upper()
        for part in str(value).strip().split(",")
    )


def _normalize_token(value: str) -> str:
    return str(value).strip().strip('"').upper()


def _first_float(value: str) -> float:
    match = re.search(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?", str(value))
    if not match:
        raise RuntimeError(f"无法从仪表响应解析数值：{value!r}")
    return float(match.group(0))


def _assert_float(actual: str, expected: float, name: str) -> None:
    value = _first_float(actual)
    if not math.isclose(value, expected, rel_tol=0.0, abs_tol=0.05):
        raise RuntimeError(f"{name}回读不一致：期望 {expected:g}，实际 {actual!r}")


def _lte_prepare_run(self: RealCMW500, com_port: int = 1, cable_loss: float = 35.0) -> None:
    """Run the fixed LTE V1 pre-connection sequence agreed for CMW500."""
    port = int(com_port)
    if port not in _COM_ROUTES:
        raise ValueError(f"LTE COM 口仅支持 COM1..COM4：COM{port}")
    loss = float(cable_loss)
    if not math.isfinite(loss) or loss < 0:
        raise ValueError(f"LTE 线损必须为非负有限数值：{cable_loss}")

    # Select LTE application before issuing LTE signaling commands.
    self._execute_operation("write", "INST LTE", "lte_prepare_run.app")

    # 1. Query COM route first; only set when it differs from the requested route.
    route_query = "ROUTe:LTE:SIGN:SCENario:SCELl?"
    expected_route = ",".join(_COM_ROUTES[port])
    current_route = self._execute_operation("query", route_query, "lte_prepare_run.com_query")
    assert current_route is not None
    if _normalize_csv(current_route) != _normalize_csv(expected_route):
        route_set = f"ROUTe:LTE:SIGN:SCENario:SCELl {expected_route}"
        self._execute_operation("write", route_set, "lte_prepare_run.com_set")
        verified_route = self._execute_operation(
            "query", route_query, "lte_prepare_run.com_verify"
        )
        assert verified_route is not None
        if _normalize_csv(verified_route) != _normalize_csv(expected_route):
            raise RuntimeError(
                f"COM{port} 路由设置后回读不一致：期望 {expected_route}，实际 {verified_route!r}"
            )

    # 2. Configure CMW500 input/output external attenuation from the LTE UI value.
    in_set = f"CONFigure:LTE:SIGN:RFSettings:EATTenuation:INPut {loss:g}"
    out_set = f"CONFigure:LTE:SIGN:RFSettings:EATTenuation:OUTPut {loss:g}"
    self._execute_operation("write", in_set, "lte_prepare_run.loss_input_set")
    self._execute_operation("write", out_set, "lte_prepare_run.loss_output_set")
    in_value = self._execute_operation(
        "query",
        "CONFigure:LTE:SIGN:RFSettings:EATTenuation:INPut?",
        "lte_prepare_run.loss_input_verify",
    )
    out_value = self._execute_operation(
        "query",
        "CONFigure:LTE:SIGN:RFSettings:EATTenuation:OUTPut?",
        "lte_prepare_run.loss_output_verify",
    )
    assert in_value is not None and out_value is not None
    _assert_float(in_value, loss, "输入线损")
    _assert_float(out_value, loss, "输出线损")
    self.current_cable_loss = loss

    # 3. Enable UE Measurement Report.
    self._execute_operation(
        "write",
        "CONFigure:LTE:SIGN:UEReport:ENABle ON",
        "lte_prepare_run.ue_report",
    )

    # 4. UE maximum uplink power: MAXP mode and P-Max = 23 dBm.
    self._execute_operation(
        "write",
        "CONFigure:LTE:SIGN:UL:PUSCh:TPC:SET MAXP",
        "lte_prepare_run.ul_tpc_maxp",
    )
    self._execute_operation(
        "write",
        "CONFigure:LTE:SIGN:UL:PMAX 23",
        "lte_prepare_run.ul_pmax",
    )

    # 5. Use Reference Measurement Channel scheduling.
    self._execute_operation(
        "write",
        "CONFigure:LTE:SIGN:CONNection:PCC:STYPe RMC",
        "lte_prepare_run.connection_rmc",
    )

    # 6. LTE security settings: all four are fixed for the V1 workflow.
    security_commands = (
        "CONFigure:LTE:SIGN:CELL:SECurity:AUTHenticat ON",
        "CONFigure:LTE:SIGN:CELL:SECurity:NAS ON",
        "CONFigure:LTE:SIGN:CELL:SECurity:AS ON",
        "CONFigure:LTE:SIGN:CELL:SECurity:IALGorithm S3G",
    )
    for index, command in enumerate(security_commands, start=1):
        self._execute_operation(
            "write", command, f"lte_prepare_run.security_{index}"
        )


def _duplex_mode_for_band(band: str) -> str:
    try:
        number = int(str(band).strip().lstrip("Bb"))
    except ValueError as exc:
        raise ValueError(f"无法识别 LTE Band：{band}") from exc
    return "TDD" if number in _TDD_BANDS else "FDD"


def _apply_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    RealCMW500.lte_prepare_run = _lte_prepare_run  # type: ignore[attr-defined]

    original_build_context = RealCMW500._build_context

    def build_context_with_duplex(self: RealCMW500, *args: Any, **kwargs: Any) -> dict[str, Any]:
        context = original_build_context(self, *args, **kwargs)
        context["duplex_mode"] = _duplex_mode_for_band(str(context.get("band", "")))
        return context

    RealCMW500._build_context = build_context_with_duplex  # type: ignore[method-assign]

    original_collect = LeftPanel.collect_lte_config

    def collect_with_com(self: LeftPanel):
        config = original_collect(self)
        combo = getattr(self, "com_port_combo", None)
        text = combo.currentText().strip().upper() if combo is not None else "COM1"
        match = re.fullmatch(r"COM([1-4])", text)
        setattr(config, "com_port", int(match.group(1)) if match else 1)
        return config

    LeftPanel.collect_lte_config = collect_with_com  # type: ignore[method-assign]

    original_template_log = TestWorker._log_real_instrument_template_state

    def prepare_run_after_template_check(self: TestWorker) -> None:
        original_template_log(self)
        method = getattr(self.instrument, "lte_prepare_run", None)
        if not callable(method):
            return
        com_port = int(getattr(self.config, "com_port", 1))
        self.log_signal.emit(
            "INFO",
            f"LTE 前置配置开始：COM{com_port}，输入/输出线损={self.config.cable_loss:g} dB",
        )
        method(com_port=com_port, cable_loss=float(self.config.cable_loss))
        self._raise_if_stopped()
        self.log_signal.emit(
            "INFO",
            "LTE 前置配置完成：COM/线损/UE Report/MAXP+P-Max/RMC/Security",
        )

    TestWorker._log_real_instrument_template_state = prepare_run_after_template_check  # type: ignore[method-assign]

    original_prepare_cell = TestWorker._call_lte_prepare_cell

    def prepare_cell_with_initial_level(self: TestWorker, item) -> None:
        # Step 7/8: the setup template reads current_rx_level and therefore sets
        # DMODE -> Band -> BW -> Channel -> initial DL power before Cell ON.
        if hasattr(self.instrument, "current_rx_level"):
            self.instrument.current_rx_level = float(self.config.start_level)
        original_prepare_cell(self, item)

    TestWorker._call_lte_prepare_cell = prepare_cell_with_initial_level  # type: ignore[method-assign]

    def measure_level_with_external_loss(
        self: TestWorker,
        item,
        dut_level: float,
        phase: str,
        current: int,
        total: int,
    ) -> bool:
        # The global UI cable loss is already configured in CMW500 EATTenuation.
        # Do not add it a second time to RS EPRE. Keep any per-channel Excel
        # correction as an additional software offset.
        total_loss = float(self.config.cable_loss) + float(item.loss_db)
        instrument_level = dut_level + float(item.loss_db)
        measured_item = replace(item, rx_level=dut_level)
        max_attempts = int(self.config.retry_count) + 1

        for attempt in range(1, max_attempts + 1):
            self._cooperate()
            self.log_signal.emit(
                "INFO",
                f"{phase} {item.band}/{item.channel} DUT={dut_level:g} dBm, "
                f"CMW RS EPRE={instrument_level:g} dBm, EATT={self.config.cable_loss:g} dB, "
                f"尝试 {attempt}/{max_attempts}",
            )
            try:
                self.instrument.set_rx_level(instrument_level)
                self._raise_if_stopped()
                self._emit_instrument_warning()
                if not self._interruptible_sleep(float(self.config.settle_time)):
                    raise _StopRequested()
                raw_bler = self.instrument.measure_bler(self.config.packet_count)
                self._raise_if_stopped()
                bler = float(raw_bler)
                result = judge_bler(bler, float(self.config.bler_threshold))
                self.data_source = self._resolve_data_source()
            except _StopRequested:
                raise
            except Exception as exc:
                status = "RETRY_PENDING" if attempt < max_attempts else "ERROR"
                test_result = self._build_result(
                    measured_item,
                    None,
                    "ERROR",
                    status,
                    attempt=attempt,
                    phase=phase,
                    instrument_level=instrument_level,
                    error_message=str(exc),
                )
                self.row_signal.emit(test_result)
                self._emit_summary(measured_item, current, total, phase, attempt)
                self.log_signal.emit(
                    "WARNING" if attempt < max_attempts else "ERROR",
                    f"测量异常（尝试 {attempt}/{max_attempts}）：{exc}",
                )
                if attempt >= max_attempts:
                    raise RuntimeError(
                        f"电平 {dut_level:g} dBm 测量异常且已耗尽重试"
                    ) from exc
                continue

            status = (
                "RETRY_PENDING"
                if result == "FAIL" and attempt < max_attempts
                else "COMPLETED"
            )
            test_result = self._build_result(
                measured_item,
                bler,
                result,
                status,
                attempt=attempt,
                phase=phase,
                instrument_level=instrument_level,
            )
            # Preserve the complete path-loss audit while recording the actual
            # CMW RS EPRE command value separately.
            test_result.total_loss = total_loss
            self.row_signal.emit(test_result)
            self._emit_summary(measured_item, current, total, phase, attempt)
            self.log_signal.emit(
                "INFO",
                f"LTE {item.band} 信道 {item.channel} DUT 电平 {dut_level:g} dBm "
                f"BLER={bler:.2f}% {result}",
            )
            if result == "PASS":
                return True
            if attempt >= max_attempts:
                return False

        raise AssertionError("unreachable")

    TestWorker._measure_level = measure_level_with_external_loss  # type: ignore[method-assign]


def apply_lte_v1_workflow() -> None:
    """Install the LTE V1 workflow hooks once during application startup."""
    _apply_patches()
