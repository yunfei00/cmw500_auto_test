from __future__ import annotations

import inspect
import math
import time
from dataclasses import asdict, replace
from typing import Any, Callable
from uuid import uuid4

from PySide6.QtCore import QObject, QMutex, QMutexLocker, Signal

from core.fake_cmw500 import FakeCMW500
from core.lte_channel_config import LTEChannelConfigManager
from core.models import LteTestConfig, TestItem, TestResult, TestRunMetadata, local_now_iso
from core.result_judge import judge_bler
from core.test_plan import generate_lte_test_plan
from core.test_states import TestState
from devices.instrument_base import InstrumentBase


class _StopRequested(RuntimeError):
    pass


class _UnsafeOperationError(RuntimeError):
    pass


class TestWorker(QObject):
    log_signal = Signal(str, str)
    row_signal = Signal(object)
    summary_signal = Signal(dict)
    finished_signal = Signal()
    state_signal = Signal(str)

    def __init__(
        self,
        config: LteTestConfig,
        lte_channel_manager: LTEChannelConfigManager | None = None,
        instrument: InstrumentBase | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.lte_channel_manager = lte_channel_manager
        self.test_plan: list[TestItem] = []
        self.instrument = instrument or FakeCMW500()
        self.run_id = run_id or config.run_id or str(uuid4())
        self.data_source = self._resolve_data_source()
        self.run_metadata = TestRunMetadata(
            run_id=self.run_id,
            data_source=self.data_source,
            instrument_mode=self.instrument.__class__.__name__,
            config_snapshot=asdict(config),
        )
        self.current_state = TestState.IDLE
        self.last_cell_key: tuple[str, int, float | None] | None = None
        self._instrument_session_started = False
        self._paused = False
        self._stopped = False
        self._cleanup_started = False
        self._mutex = QMutex()

    def run(self) -> None:
        outcome = TestState.FAILED
        after_measure_needed = False
        unsafe_operation = False

        try:
            self._raise_if_stopped()
            self.set_state(TestState.PREPARING, "状态切换：PREPARING - 准备测试")
            self._validate_config()
            self.log_signal.emit("INFO", "开始生成 LTE 测试计划")
            self.test_plan = generate_lte_test_plan(self.config, self.lte_channel_manager)
            self._validate_test_plan()
            total = len(self.test_plan)
            self.log_signal.emit("INFO", f"共生成 {total} 个信道测试项")

            self._prepare_instrument_for_run()
            instrument_type = self.instrument.__class__.__name__
            self.log_signal.emit("INFO", f"当前使用仪表类型：{instrument_type}")
            if not self._ensure_instrument_connected():
                raise RuntimeError("仪表连接失败")
            self._instrument_session_started = True

            self._log_real_instrument_template_state()

            for current, item in enumerate(self.test_plan, start=1):
                self._cooperate()
                cell_key = (item.band, item.channel, item.bw)
                if self.last_cell_key != cell_key:
                    if self.last_cell_key is not None and not self._safe_cell_off():
                        unsafe_operation = True
                        raise _UnsafeOperationError("切换信道前 Cell OFF 失败")
                    self._prepare_cell(item)
                    after_measure_needed = True
                    self.last_cell_key = cell_key

                self.set_state(
                    TestState.MEASURING,
                    "状态切换：MEASURING - 开始灵敏度扫描",
                )
                if not self._measure_item(item, current, total):
                    outcome = TestState.FAILED
                    break
            else:
                outcome = TestState.COMPLETED

            if self._is_stopped():
                outcome = TestState.STOPPED
        except _StopRequested:
            outcome = TestState.STOPPED
            self.log_signal.emit("INFO", "测试已收到停止请求，正在安全收尾")
        except _UnsafeOperationError as exc:
            unsafe_operation = True
            outcome = TestState.FAILED
            self.log_signal.emit("ERROR", str(exc))
        except Exception as exc:
            outcome = TestState.FAILED
            self.log_signal.emit("ERROR", f"测试流程异常：{exc}")
        finally:
            with QMutexLocker(self._mutex):
                self._cleanup_started = True
                self._paused = False
            cleanup_connection_ok = self._prepare_instrument_for_cleanup()
            if after_measure_needed:
                try:
                    self._run_after_measure()
                except Exception as exc:
                    outcome = TestState.FAILED
                    self.log_signal.emit("ERROR", f"测量后处理异常：{exc}")

            if self._instrument_session_started:
                cleanup_safe = self._safe_cell_off_and_cleanup() and cleanup_connection_ok
            else:
                cleanup_safe = True
            self._disconnect_instrument_session()
            if not cleanup_safe or unsafe_operation:
                final_state = TestState.FAILED_UNSAFE
                final_message = "测试结束，但仪表安全清理未确认完成"
            elif self._is_stopped() or outcome is TestState.STOPPED:
                final_state = TestState.STOPPED
                final_message = "测试已停止并完成安全清理"
            elif outcome is TestState.COMPLETED:
                final_state = TestState.COMPLETED
                final_message = "测试完成"
            else:
                final_state = TestState.FAILED
                final_message = "测试失败"

            self.set_state(final_state, f"状态切换：{final_state.value} - {final_message}")
            self.log_signal.emit(
                "ERROR" if final_state in {TestState.FAILED, TestState.FAILED_UNSAFE} else "INFO",
                final_message,
            )
            self.run_metadata.status = final_state.value
            self.run_metadata.end_time = local_now_iso()
            self.run_metadata.data_source = self.data_source
            self.finished_signal.emit()

    def _disconnect_instrument_session(self) -> None:
        if not self._instrument_session_started:
            return
        disconnect = getattr(self.instrument, "disconnect", None)
        if callable(disconnect):
            try:
                disconnect()
            except Exception as exc:
                self.log_signal.emit("WARNING", f"测试结束后断开仪表会话失败：{exc}")
        self._instrument_session_started = False

    def set_state(self, state: TestState, message: str = "") -> None:
        self.current_state = state
        self.run_metadata.status = state.value
        self.state_signal.emit(state.value)
        self.log_signal.emit("INFO", message or f"状态切换：{state.value}")

    def _validate_config(self) -> None:
        numeric_values = {
            "start_level": self.config.start_level,
            "stop_level": self.config.stop_level,
            "max_step": self.config.max_step,
            "min_step": self.config.min_step,
            "cable_loss": self.config.cable_loss,
            "bler_threshold": self.config.bler_threshold,
            "sensitivity_upper": self.config.sensitivity_upper,
        }
        for name, value in numeric_values.items():
            if not math.isfinite(float(value)):
                raise ValueError(f"{name} 必须是有限数值")
        if self.config.max_step <= 0 or self.config.min_step <= 0:
            raise ValueError("max_step 和 min_step 必须大于 0")
        if self.config.max_step < self.config.min_step:
            raise ValueError("max_step 不能小于 min_step")
        if self.config.start_level <= self.config.stop_level:
            raise ValueError("start_level 必须大于 stop_level")
        if self.config.cable_loss < 0:
            raise ValueError("cable_loss 不能小于 0")
        if self.config.packet_count <= 0:
            raise ValueError("packet_count 必须大于 0")
        if self.config.retry_count < 0:
            raise ValueError("retry_count 不能小于 0")
        if self.config.settle_time < 0:
            raise ValueError("settle_time 不能小于 0")
        judge_bler(0.0, float(self.config.bler_threshold))

    def _validate_test_plan(self) -> None:
        if not self.test_plan:
            raise ValueError("LTE 测试计划为空，禁止生成 COMPLETED 结果")
        for item in self.test_plan:
            if not item.band.strip():
                raise ValueError(f"测试项 {item.index} 的 Band 为空")
            if item.channel < 0:
                raise ValueError(f"测试项 {item.index} 的信道不能为负数")
            if item.bw is None or not math.isfinite(float(item.bw)) or item.bw <= 0:
                raise ValueError(f"测试项 {item.index} 的带宽必须是大于 0 的有限数值")
            if not math.isfinite(float(item.loss_db)) or item.loss_db < 0:
                raise ValueError(f"测试项 {item.index} 的信道线损必须是非负有限数值")

    def _ensure_instrument_connected(self) -> bool:
        try:
            if not self.instrument.is_connected():
                self.instrument.connect()
            validate_idn = getattr(self.instrument, "query_and_validate_idn", None)
            if callable(validate_idn):
                instrument_idn = str(validate_idn()).strip()
                self.run_metadata.instrument_idn = instrument_idn
                self.log_signal.emit("INFO", f"测试前仪表身份确认：{instrument_idn}")
            self._raise_if_stopped()
        except _StopRequested:
            raise
        except Exception as exc:
            self.log_signal.emit("ERROR", f"仪表连接失败，测试终止：{exc}")
            return False
        return True

    def _prepare_instrument_for_run(self) -> None:
        clear_cancel = getattr(self.instrument, "clear_cancel", None)
        if clear_cancel:
            clear_cancel()
        set_cancel_checker = getattr(self.instrument, "set_cancel_checker", None)
        if set_cancel_checker:
            set_cancel_checker(self._is_stopped)

    def _prepare_instrument_for_cleanup(self) -> bool:
        """Remove cancellation and restore I/O so emergency Cell OFF can run."""

        try:
            set_cancel_checker = getattr(self.instrument, "set_cancel_checker", None)
            if set_cancel_checker:
                set_cancel_checker(None)
            clear_cancel = getattr(self.instrument, "clear_cancel", None)
            if clear_cancel:
                clear_cancel()
            if self._instrument_session_started and not self.instrument.is_connected():
                self.log_signal.emit(
                    "WARNING", "仪表连接在取消期间已关闭，正在重连以执行安全清理"
                )
                self.instrument.connect()
            return True
        except Exception as exc:
            self.log_signal.emit("ERROR", f"恢复仪表连接以执行安全清理失败：{exc}")
            return False

    def _log_real_instrument_template_state(self) -> None:
        if self.instrument.__class__.__name__ != "RealCMW500":
            return
        manager = getattr(self.instrument, "scpi_template_manager", None)
        has_template = bool(manager and manager.has_template())
        self.log_signal.emit(
            "INFO", f"RealCMW500 SCPI 模板已加载：{'是' if has_template else '否'}"
        )
        if has_template:
            self.log_signal.emit("INFO", "使用 CMW500 SCPI 模板执行 LTE 测试流程")
        else:
            self.log_signal.emit("WARNING", "未加载 SCPI 模板，真实测试将无法继续")

    def _prepare_cell(self, item: TestItem) -> None:
        self.set_state(
            TestState.CELL_CONFIGURING,
            f"状态切换：CELL_CONFIGURING - 配置 LTE 小区 {item.band}/{item.channel}",
        )
        self._call_lte_prepare_cell(item)
        self._raise_if_stopped()
        self._emit_instrument_warning()
        self.log_signal.emit(
            "INFO",
            f"LTE 小区配置完成：{item.band} 信道 {item.channel} BW={item.bw}",
        )

        self.set_state(TestState.CELL_ON, "状态切换：CELL_ON - LTE Cell ON")
        self._call_lte_cell_on(item)
        self._raise_if_stopped()
        self._emit_instrument_warning()

        self.set_state(
            TestState.WAITING_ATTACH,
            "状态切换：WAITING_ATTACH - 等待 UE Attach",
        )
        if not self._call_wait_for_attach():
            self._emit_instrument_warning()
            raise RuntimeError("UE Attach 检查失败或超时")
        self._raise_if_stopped()
        self._emit_instrument_warning()
        self.set_state(TestState.ATTACHED, "状态切换：ATTACHED - UE 已连接")
        self.log_signal.emit("INFO", "UE Attach 检查通过")
        self._run_before_measure()

    def _measure_item(self, item: TestItem, current: int, total: int) -> bool:
        try:
            self._scan_item(item, current, total)
            return True
        except _StopRequested:
            raise
        except Exception as exc:
            self.log_signal.emit("ERROR", f"测试项 {item.index} 执行异常：{exc}")
            return False

    def _scan_item(self, item: TestItem, current: int, total: int) -> None:
        direction = 1.0 if self.config.stop_level > self.config.start_level else -1.0
        level = float(self.config.start_level)
        stop_level = float(self.config.stop_level)
        last_pass_level: float | None = None

        while True:
            passed = self._measure_level(item, level, "COARSE", current, total)
            if passed:
                last_pass_level = level
            else:
                if last_pass_level is not None:
                    self._fine_scan(
                        item,
                        last_pass_level,
                        level,
                        direction,
                        current,
                        total,
                    )
                return

            if self._same_level(level, stop_level):
                return
            level = self._next_level(level, stop_level, self.config.max_step, direction)

    def _fine_scan(
        self,
        item: TestItem,
        pass_level: float,
        fail_level: float,
        direction: float,
        current: int,
        total: int,
    ) -> None:
        level = self._next_level(pass_level, fail_level, self.config.min_step, direction)
        while not self._same_level(level, fail_level):
            if not self._measure_level(item, level, "FINE", current, total):
                return
            level = self._next_level(level, fail_level, self.config.min_step, direction)

    def _measure_level(
        self,
        item: TestItem,
        dut_level: float,
        phase: str,
        current: int,
        total: int,
    ) -> bool:
        total_loss = float(self.config.cable_loss) + float(item.loss_db)
        instrument_level = dut_level + total_loss
        measured_item = replace(item, rx_level=dut_level)
        max_attempts = int(self.config.retry_count) + 1

        for attempt in range(1, max_attempts + 1):
            self._cooperate()
            self.log_signal.emit(
                "INFO",
                f"{phase} {item.band}/{item.channel} DUT={dut_level:g} dBm, "
                f"仪表={instrument_level:g} dBm, 尝试 {attempt}/{max_attempts}",
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

            status = "RETRY_PENDING" if result == "FAIL" and attempt < max_attempts else "COMPLETED"
            test_result = self._build_result(
                measured_item,
                bler,
                result,
                status,
                attempt=attempt,
                phase=phase,
                instrument_level=instrument_level,
            )
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

    @staticmethod
    def _next_level(current: float, target: float, step: float, direction: float) -> float:
        candidate = current + direction * float(step)
        if (direction > 0 and candidate > target) or (direction < 0 and candidate < target):
            candidate = target
        return round(candidate, 10)

    @staticmethod
    def _same_level(left: float, right: float) -> bool:
        return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)

    def _run_before_measure(self) -> None:
        self.log_signal.emit("INFO", "执行测量前命令")
        self._call_optional("lte_before_measure")
        self._raise_if_stopped()
        self._emit_instrument_warning()

    def _run_after_measure(self) -> None:
        self.log_signal.emit("INFO", "执行测量后命令")
        self._call_optional("lte_after_measure")
        self._emit_instrument_warning()

    def _safe_cell_off_and_cleanup(self) -> bool:
        self.set_state(TestState.CLEANUP, "状态切换：CLEANUP - 清理测试环境")
        cell_off_ok = self._safe_cell_off()
        cleanup_ok = self._safe_cleanup()
        return cell_off_ok and cleanup_ok

    def _safe_cell_off(self) -> bool:
        try:
            self.log_signal.emit("INFO", "Cell OFF")
            self._call_optional("lte_cell_off")
            self._emit_instrument_warning()
            return True
        except Exception as exc:
            self.log_signal.emit("ERROR", f"Cell OFF 异常：{exc}")
            return False

    def _safe_cleanup(self) -> bool:
        try:
            self.log_signal.emit("INFO", "Cleanup")
            self._call_optional("lte_cleanup")
            self._emit_instrument_warning()
            return True
        except Exception as exc:
            self.log_signal.emit("ERROR", f"Cleanup 异常：{exc}")
            return False

    def _call_lte_prepare_cell(self, item: TestItem) -> None:
        method = getattr(self.instrument, "lte_prepare_cell", None)
        if method:
            self._call_with_supported_kwargs(
                method,
                item.band,
                item.channel,
                channel_type=item.channel_type,
                test_mode=item.test_mode,
                bw=item.bw,
                packet_count=self.config.packet_count,
                cable_loss=float(self.config.cable_loss) + float(item.loss_db),
            )
            return
        self._setup_lte_compat(item)

    def _call_lte_cell_on(self, item: TestItem) -> None:
        method = getattr(self.instrument, "lte_cell_on", None)
        if method:
            self._call_with_supported_kwargs(
                method,
                item.band,
                item.channel,
                channel_type=item.channel_type,
                test_mode=item.test_mode,
            )

    def _call_wait_for_attach(self) -> bool:
        method = getattr(self.instrument, "wait_for_attach", None)
        if not method:
            return True
        result = self._call_with_supported_kwargs(method, cancel_check=self._is_stopped)
        return bool(result)

    @staticmethod
    def _call_with_supported_kwargs(
        method: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return method(*args, **kwargs)

        accepts_var_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if accepts_var_kwargs:
            supported = kwargs
        else:
            supported = {key: value for key, value in kwargs.items() if key in signature.parameters}
        return method(*args, **supported)

    def _call_optional(self, method_name: str) -> Any:
        method = getattr(self.instrument, method_name, None)
        if method:
            return method()
        return None

    def _setup_lte_compat(self, item: TestItem) -> None:
        method = self.instrument.setup_lte
        self._call_with_supported_kwargs(
            method,
            item.band,
            item.channel,
            channel_type=item.channel_type,
            test_mode=item.test_mode,
            bw=item.bw,
            packet_count=self.config.packet_count,
            cable_loss=float(self.config.cable_loss) + float(item.loss_db),
        )

    def _emit_instrument_warning(self) -> None:
        warning = getattr(self.instrument, "last_warning", "")
        if warning:
            self.log_signal.emit("WARNING", str(warning))
            try:
                self.instrument.last_warning = ""
            except Exception:
                pass

    def _emit_summary(
        self,
        item: TestItem,
        current: int,
        total: int,
        phase: str,
        attempt: int,
    ) -> None:
        self.summary_signal.emit(
            {
                "run_id": self.run_id,
                "data_source": self.data_source,
                "scan_phase": phase,
                "attempt": attempt,
                "current_mode": "LTE",
                "current_band": item.band,
                "current_channel": str(item.channel),
                "current_level": f"{item.rx_level:g} dBm",
                "progress": f"{current}/{total}",
            }
        )

    def _build_result(
        self,
        item: TestItem,
        bler: float | None,
        result: str,
        status: str,
        *,
        attempt: int = 1,
        phase: str = "COARSE",
        instrument_level: float | None = None,
        error_message: str = "",
    ) -> TestResult:
        total_loss = float(self.config.cable_loss) + float(item.loss_db)
        if instrument_level is None:
            instrument_level = item.rx_level + total_loss
        return TestResult(
            index=item.index,
            mode=item.mode,
            band=item.band,
            channel=item.channel,
            channel_type=item.channel_type,
            test_mode=item.test_mode,
            rx_level=item.rx_level,
            metric_type="BLER",
            metric_value=bler,
            result=result,
            status=status,
            run_id=self.run_id,
            data_source=self.data_source,
            bw=item.bw,
            global_cable_loss=float(self.config.cable_loss),
            channel_loss=float(item.loss_db),
            total_loss=total_loss,
            instrument_level=instrument_level,
            packet_count=int(self.config.packet_count),
            bler_threshold=float(self.config.bler_threshold),
            sensitivity_upper=float(self.config.sensitivity_upper),
            attempt=attempt,
            scan_phase=phase,
            error_message=error_message,
        )

    def _resolve_data_source(self) -> str:
        for attribute in ("last_measurement_source", "data_source"):
            value = getattr(self.instrument, attribute, "")
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = ""
            if value:
                normalized = str(value).strip().upper()
                if normalized in {"FAKE", "SIMULATED", "SIMULATION"}:
                    return "SIMULATION"
                if normalized in {"INSTRUMENT", "REAL", "REAL_CMW500"}:
                    return "REAL"
                return normalized
        if isinstance(self.instrument, FakeCMW500):
            return "SIMULATION"
        return "INSTRUMENT"

    def pause(self) -> None:
        with QMutexLocker(self._mutex):
            self._paused = True
        self.set_state(TestState.PAUSED, "状态切换：PAUSED - 测试已暂停")

    def resume(self) -> None:
        with QMutexLocker(self._mutex):
            self._paused = False
        self.set_state(TestState.MEASURING, "状态切换：MEASURING - 测试继续")

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            if self._stopped:
                return
            self._stopped = True
            self._paused = False
            cleanup_started = self._cleanup_started
        self.set_state(TestState.STOPPING, "状态切换：STOPPING - 请求停止测试")
        if cleanup_started:
            self.log_signal.emit("INFO", "安全清理已经开始；停止请求不会再次中断仪表 I/O")
            return
        for method_name in ("request_cancel", "abort_io"):
            method = getattr(self.instrument, method_name, None)
            if not method:
                continue
            try:
                method()
            except Exception as exc:
                self.log_signal.emit("WARNING", f"{method_name} 调用失败：{exc}")

    def _is_stopped(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stopped

    def _is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._paused

    def _raise_if_stopped(self) -> None:
        if self._is_stopped():
            raise _StopRequested()

    def _cooperate(self) -> None:
        self._wait_if_paused()
        self._raise_if_stopped()

    def _wait_if_paused(self) -> None:
        while self._is_paused() and not self._is_stopped():
            time.sleep(0.05)

    def _interruptible_sleep(self, seconds: float) -> bool:
        remaining = max(0.0, seconds)
        while remaining > 0:
            self._cooperate()
            chunk = min(0.05, remaining)
            started = time.monotonic()
            time.sleep(chunk)
            remaining -= max(0.0, time.monotonic() - started)
        return not self._is_stopped()
