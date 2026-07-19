from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from core.scpi_template import ScpiCommand, ScpiTemplateManager
from devices.instrument_base import InstrumentBase
from devices.instrument_transport import (
    InstrumentCancelledError,
    InstrumentTransport,
    SocketTransport,
)


def is_cmw500_idn(response: str) -> bool:
    """Return whether an IDN response identifies an R&S CMW/CMW500."""

    normalized = " ".join(str(response).strip().upper().split())
    has_vendor = ("ROHDE" in normalized and "SCHWARZ" in normalized) or "R&S" in normalized
    has_model = re.search(r"(?:^|[\s,])CMW(?:500)?(?:[\s,]|$)", normalized) is not None
    return bool(has_vendor and has_model)


def validate_cmw500_idn(response: str) -> str:
    """Validate and return a CMW500 IDN response, otherwise fail closed."""

    value = str(response).strip()
    if not value:
        raise RuntimeError("CMW500 *IDN? 返回为空")
    if not is_cmw500_idn(value):
        raise RuntimeError(f"连接的仪表不是受支持的 R&S CMW500：{value}")
    return value


class RealCMW500(InstrumentBase):
    """Real CMW500 controller.

    This class never fabricates a measurement. The legacy
    ``fallback_simulation`` argument is accepted for API compatibility only and
    has no effect; all transport, timeout and parser errors are propagated.
    """

    is_simulation = False
    data_source = "REAL_CMW500"

    def __init__(
        self,
        transport: InstrumentTransport,
        fallback_simulation: bool = False,
    ) -> None:
        self.transport = transport
        self.fallback_simulation = False
        self.fallback_simulation_requested = bool(fallback_simulation)
        self.scpi_template_manager: ScpiTemplateManager | None = None
        self.current_band = ""
        self.current_channel = 0
        self.current_channel_type = ""
        self.current_test_mode = ""
        self.current_rx_level = -70.0
        self.current_bandwidth: float | str = 20.0
        self.current_packet_count = 1000
        self.current_cable_loss = 0.0
        self.last_warning = (
            "RealCMW500 已忽略不安全的 fallback_simulation=True；真实测量不会回退模拟值"
            if self.fallback_simulation_requested
            else ""
        )
        self.last_attach_response = ""
        self.last_commands: list[str] = []
        self.command_trace: list[dict[str, Any]] = []
        # Compatibility alias for callers that prefer an explicit last-run name.
        self.last_command_trace = self.command_trace
        self._cancel_event = threading.Event()
        self._cancel_checker: Callable[[], bool] | None = None
        self.transport.set_cancel_checker(self._is_cancel_requested)

    def connect(self) -> None:
        self.clear_cancel()
        self.transport.connect()

    def disconnect(self) -> None:
        self.transport.close()

    def is_connected(self) -> bool:
        return self.transport.is_connected()

    def query_idn(self) -> str:
        response = self._execute_operation(
            operation="query", command="*IDN?", stage="query_idn"
        )
        assert response is not None
        return response

    def query_and_validate_idn(self) -> str:
        return validate_cmw500_idn(self.query_idn())

    def validate_idn(self, response: str | None = None) -> str:
        return validate_cmw500_idn(self.query_idn() if response is None else response)

    def write(self, command: str) -> None:
        self._execute_operation("write", command, "direct")

    def query(self, command: str) -> str:
        response = self._execute_operation("query", command, "direct")
        assert response is not None
        return response

    @classmethod
    def from_socket(
        cls,
        host: str,
        port: int = 5025,
        timeout_ms: int = 10000,
        fallback_simulation: bool = False,
    ) -> "RealCMW500":
        return cls(
            SocketTransport(host, port, timeout_ms),
            fallback_simulation=fallback_simulation,
        )

    def reset(self) -> None:
        self._execute_operation("write", "*RST", "reset")

    def preset(self) -> None:
        self._execute_operation("write", "SYST:PRES", "preset")

    def set_scpi_template_manager(self, manager: ScpiTemplateManager | None) -> None:
        self.scpi_template_manager = manager
        template = manager.get_lte_template() if manager else None
        if template and template.measure_bler.fallback_simulation:
            self.last_warning = (
                "SCPI 模板中的 fallback_simulation=true 已被忽略；Real 模式始终 fail-closed"
            )

    def clear_command_trace(self) -> None:
        self.command_trace.clear()
        self.last_commands.clear()

    def execute_template_commands(
        self,
        commands: list[ScpiCommand] | list[Any],
        context: dict[str, Any],
        stage: str = "",
    ) -> list[str | None]:
        if not commands:
            return []
        manager = self._require_template_manager()

        responses: list[str | None] = []
        for index, raw_command in enumerate(commands):
            spec = manager.parse_command(raw_command, f"{stage or 'commands'}[{index}]")
            command = manager.render_command(spec.command, context)
            responses.append(
                self._execute_operation(
                    operation=spec.operation,
                    command=command,
                    stage=stage,
                    parser=spec.parser,
                    expected=spec.expected,
                )
            )
        return responses

    def lte_prepare_cell(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
        bw: float | None = None,
        packet_count: int | None = None,
        cable_loss: float | None = None,
    ) -> None:
        self.current_band = band
        self.current_channel = channel
        self.current_channel_type = channel_type
        self.current_test_mode = test_mode
        if bw is not None:
            self.current_bandwidth = bw
        if packet_count is not None:
            self.current_packet_count = int(packet_count)
        if cable_loss is not None:
            self.current_cable_loss = float(cable_loss)

        template = self._require_lte_template()
        if not template.setup:
            raise RuntimeError("LTE SCPI 模板未配置 setup 命令")
        self.execute_template_commands(
            template.setup,
            self._build_context(
                band=band,
                channel=channel,
                channel_type=channel_type,
                test_mode=test_mode,
                bw=bw,
                packet_count=packet_count,
                cable_loss=cable_loss,
            ),
            "lte_prepare_cell",
        )

    def lte_cell_on(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        self.current_band = band
        self.current_channel = channel
        self.current_channel_type = channel_type
        self.current_test_mode = test_mode
        template = self._require_lte_template()
        if not template.cell_on:
            raise RuntimeError("LTE SCPI 模板未配置 cell_on 命令")
        self.execute_template_commands(
            template.cell_on,
            self._build_context(
                band=band,
                channel=channel,
                channel_type=channel_type,
                test_mode=test_mode,
            ),
            "lte_cell_on",
        )

    def wait_for_attach(
        self,
        timeout: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        template = self._require_lte_template()
        manager = self._require_template_manager()
        if not template.wait_attach:
            raise RuntimeError("LTE SCPI 模板未配置 wait_attach")

        wait_config = template.wait_attach
        timeout_sec = timeout if timeout is not None else wait_config.timeout_sec
        timeout_sec = max(float(timeout_sec), 0.0)
        interval_sec = max(float(wait_config.interval_sec), 0.01)
        deadline = time.monotonic() + timeout_sec
        context = self._build_context(
            band=self.current_band,
            channel=self.current_channel,
            rx_level=self.current_rx_level,
            channel_type=self.current_channel_type,
            test_mode=self.current_test_mode,
        )
        command = manager.render_command(wait_config.query, context)

        while True:
            if cancel_check is not None and cancel_check():
                raise InstrumentCancelledError("等待 UE Attach 已取消")
            response = self._execute_operation(
                operation="query", command=command, stage="wait_attach"
            )
            assert response is not None
            self.last_attach_response = response
            if manager.parse_wait_response(
                response, wait_config.parser, wait_config.expected
            ):
                return True
            if manager.last_parse_error:
                raise RuntimeError(manager.last_parse_error)
            if time.monotonic() >= deadline:
                self.last_warning = (
                    f"wait_attach 超时，最后响应：{self.last_attach_response or '-'}"
                )
                return False
            self._sleep_cancelable(
                min(interval_sec, max(deadline - time.monotonic(), 0.0))
            )

    def lte_before_measure(self) -> None:
        template = self._require_lte_template()
        self.execute_template_commands(
            template.before_measure,
            self._build_context(self.current_band, self.current_channel),
            "lte_before_measure",
        )

    def lte_after_measure(self) -> None:
        template = self._require_lte_template()
        self.execute_template_commands(
            template.after_measure,
            self._build_context(self.current_band, self.current_channel),
            "lte_after_measure",
        )

    def lte_cell_off(self) -> None:
        template = self._require_lte_template()
        if not template.cell_off:
            raise RuntimeError("LTE SCPI 模板未配置 cell_off 命令")
        self.execute_template_commands(
            template.cell_off,
            self._build_context(self.current_band, self.current_channel),
            "lte_cell_off",
        )

    def lte_cleanup(self) -> None:
        template = self._require_lte_template()
        self.execute_template_commands(
            template.cleanup,
            self._build_context(self.current_band, self.current_channel),
            "lte_cleanup",
        )

    def setup_lte(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
        bw: float | None = None,
        packet_count: int | None = None,
        cable_loss: float | None = None,
    ) -> None:
        self.lte_prepare_cell(
            band,
            channel,
            channel_type,
            test_mode,
            bw=bw,
            packet_count=packet_count,
            cable_loss=cable_loss,
        )

    def set_rx_level(self, level: float) -> None:
        value = float(level)
        if not math.isfinite(value):
            raise ValueError(f"RX Level 必须是有限数值：{level}")
        self.current_rx_level = value
        template = self._require_lte_template()
        if not template.set_rx_level:
            raise RuntimeError("LTE SCPI 模板未配置 set_rx_level 命令")
        context = self._build_context(
            band=self.current_band,
            channel=self.current_channel,
            rx_level=value,
            channel_type=self.current_channel_type,
            test_mode=self.current_test_mode,
        )
        self.execute_template_commands(template.set_rx_level, context, "set_rx_level")

    def measure_bler(self, packet_count: int) -> float:
        template = self._require_lte_template()
        manager = self._require_template_manager()
        measure_config = template.measure_bler
        self.current_packet_count = int(packet_count)
        if self.current_packet_count <= 0:
            raise ValueError(f"packet_count 必须大于 0：{packet_count}")
        context = self._build_context(
            band=self.current_band,
            channel=self.current_channel,
            rx_level=self.current_rx_level,
            packet_count=self.current_packet_count,
            channel_type=self.current_channel_type,
            test_mode=self.current_test_mode,
        )

        result: float | None = None
        measurement_error: Exception | None = None
        try:
            self.execute_template_commands(
                measure_config.start, context, "measure_bler.start"
            )
            if measure_config.state_query:
                deadline = time.monotonic() + max(
                    float(measure_config.state_timeout_sec), 0.0
                )
                interval = max(float(measure_config.state_interval_sec), 0.01)
                state_command = manager.render_command(measure_config.state_query, context)
                while True:
                    state_response = self._execute_operation(
                        "query", state_command, "measure_bler.state"
                    )
                    assert state_response is not None
                    if manager.parse_wait_response(
                        state_response,
                        measure_config.state_parser,
                        measure_config.state_done,
                    ):
                        break
                    if manager.last_parse_error:
                        raise RuntimeError(manager.last_parse_error)
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "BLER 测量状态等待超时："
                            f"query={state_command}, response={state_response}"
                        )
                    self._sleep_cancelable(
                        min(interval, max(deadline - time.monotonic(), 0.0))
                    )

            command = manager.render_command(measure_config.query, context)
            response = self._execute_operation("query", command, "measure_bler.query")
            assert response is not None
            result = manager.parse_measure_response(response, measure_config.parser)
            if not math.isfinite(result) or not 0.0 <= result <= 100.0:
                raise ValueError(
                    f"BLER 超出有效范围 0..100：{result}，原始响应：{response}"
                )
        except Exception as exc:
            measurement_error = exc

        stop_error: Exception | None = None
        try:
            self.execute_template_commands(
                measure_config.stop, context, "measure_bler.stop"
            )
        except Exception as exc:
            stop_error = exc

        if measurement_error is not None and stop_error is not None:
            raise RuntimeError(
                f"BLER 测量失败且停止命令也失败：measure={measurement_error}; stop={stop_error}"
            ) from measurement_error
        if measurement_error is not None:
            raise measurement_error
        if stop_error is not None:
            raise stop_error
        assert result is not None
        return result

    def set_cancel_checker(self, checker: Callable[[], bool] | None) -> None:
        self._cancel_checker = checker

    def request_cancel(self) -> None:
        self._cancel_event.set()
        self.transport.request_cancel()

    def clear_cancel(self) -> None:
        self._cancel_event.clear()
        self.transport.clear_cancel()

    def abort_io(self) -> None:
        self._cancel_event.set()
        self.transport.abort_io()

    def _build_context(
        self,
        band: str,
        channel: int,
        rx_level: float | None = None,
        packet_count: int | None = None,
        channel_type: str | None = None,
        test_mode: str | None = None,
        bw: float | str | None = None,
        cable_loss: float | None = None,
    ) -> dict[str, Any]:
        band_number = str(band).lstrip("Bb")
        bandwidth = self.current_bandwidth if bw is None else bw
        packets = self.current_packet_count if packet_count is None else int(packet_count)
        loss = self.current_cable_loss if cable_loss is None else float(cable_loss)
        return {
            "mode": "LTE",
            "band": band,
            "band_number": band_number,
            "channel": channel,
            "channel_type": (
                channel_type if channel_type is not None else self.current_channel_type
            ),
            "rx_level": self.current_rx_level if rx_level is None else rx_level,
            "packet_count": packets,
            "test_mode": test_mode if test_mode is not None else self.current_test_mode,
            "bw": bandwidth,
            "bandwidth": bandwidth,
            "cable_loss": loss,
        }

    def _execute_operation(
        self,
        operation: str,
        command: str,
        stage: str,
        parser: str = "equals",
        expected: str = "",
    ) -> str | None:
        self._check_cancelled()
        self.last_commands.append(command)
        response: str | None = None
        try:
            if operation == "write":
                self.transport.write(command)
            elif operation in {"query", "query_and_assert"}:
                response = self.transport.query(command)
                if operation == "query_and_assert":
                    manager = self._require_template_manager()
                    if not manager.parse_wait_response(response, parser, expected):
                        detail = manager.last_parse_error or (
                            f"响应断言失败：parser={parser}, expected={expected!r}, "
                            f"response={response!r}"
                        )
                        raise RuntimeError(detail)
            else:
                raise ValueError(f"不支持的 SCPI 操作：{operation}")
        except Exception as exc:
            self._append_trace(stage, operation, command, response, False, str(exc))
            if isinstance(exc, InstrumentCancelledError):
                raise
            stage_text = f"{stage} " if stage else ""
            raise RuntimeError(
                f"{stage_text}SCPI {operation} 执行失败：{command}，{exc}"
            ) from exc

        self._append_trace(stage, operation, command, response, True, "")
        return response

    def _append_trace(
        self,
        stage: str,
        operation: str,
        command: str,
        response: str | None,
        success: bool,
        error: str,
    ) -> None:
        self.command_trace.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "operation": operation,
                "command": command,
                "response": response,
                "success": success,
                "error": error,
            }
        )

    def _is_cancel_requested(self) -> bool:
        if self._cancel_event.is_set():
            return True
        return bool(self._cancel_checker()) if self._cancel_checker is not None else False

    def _check_cancelled(self) -> None:
        if self._is_cancel_requested():
            raise InstrumentCancelledError("仪表操作已取消")

    def _sleep_cancelable(self, duration: float) -> None:
        deadline = time.monotonic() + max(float(duration), 0.0)
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.05))

    def _require_template_manager(self) -> ScpiTemplateManager:
        if self.scpi_template_manager is None:
            raise RuntimeError("未加载 SCPI 模板管理器")
        return self.scpi_template_manager

    def _require_lte_template(self):
        manager = self._require_template_manager()
        template = manager.get_lte_template()
        if template is None:
            raise RuntimeError("未加载 LTE SCPI 模板")
        return template
