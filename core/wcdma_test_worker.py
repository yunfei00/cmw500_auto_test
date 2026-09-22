from __future__ import annotations

import math
from dataclasses import asdict
from uuid import uuid4

from PySide6.QtCore import QObject, QMutex, QMutexLocker, Signal

from core.fake_cmw500 import FakeCMW500
from core.models import TestResult, TestRunMetadata, WcdmaTestConfig, local_now_iso
from core.test_states import TestState
from core.wcdma_sensitivity import search_wcdma_sensitivity
from devices.instrument_base import InstrumentBase


class _StopRequested(RuntimeError):
    pass


class WcdmaTestWorker(QObject):
    """WCDMA Band -> Channel -> Scene -> sensitivity execution worker."""

    log_signal = Signal(str, str)
    row_signal = Signal(object)
    summary_signal = Signal(dict)
    finished_signal = Signal()
    state_signal = Signal(str)

    def __init__(self, config: WcdmaTestConfig, instrument: InstrumentBase, run_id: str | None = None) -> None:
        super().__init__()
        self.config = config
        self.instrument = instrument
        self.run_id = run_id or uuid4().hex
        self.data_source = "SIMULATION" if isinstance(instrument, FakeCMW500) else "INSTRUMENT"
        self.run_metadata = TestRunMetadata(run_id=self.run_id, data_source=self.data_source, instrument_mode=instrument.__class__.__name__, config_snapshot=asdict(config))
        self.current_state = TestState.IDLE
        self._paused = False
        self._stopped = False
        self._cleanup_started = False
        self._instrument_session_started = False
        self._mutex = QMutex()

    def run(self) -> None:
        outcome = TestState.FAILED
        unsafe = False
        try:
            self._validate_config()
            self.set_state(TestState.PREPARING, "状态切换：PREPARING - 准备 WCDMA 测试")
            self._prepare_instrument()
            self._debug("开始 WCDMA 公共初始化", com_port=self.config.com_port, cable_loss=self.config.cable_loss)
            self.instrument.wcdma_prepare_run(com_port=self.config.com_port, cable_loss=self.config.cable_loss)
            self._debug("WCDMA 公共初始化完成")
            self._raise_if_stopped()
            total = sum(len(self.config.channels_by_band.get(b, [])) * len(self.config.scenes) for b in self.config.selected_bands)
            current = 0
            for band in self.config.selected_bands:
                self._cooperate()
                self._debug("设置 Band", band=band)
                self.instrument.wcdma_set_band(band)
                self._debug("设置 Band 初始功率", band=band, power=self.config.power)
                self.instrument.wcdma_set_power(self.config.power)
                for channel in self.config.channels_by_band.get(band, []):
                    self._cooperate()
                    self._debug("设置 Channel", band=band, channel=channel)
                    self.instrument.wcdma_set_channel(channel)
                    self._debug("设置建链电平", level=self.config.connection_level)
                    self.instrument.wcdma_set_power(self.config.connection_level)
                    self._debug("准备 Cell ON", band=band, channel=channel)
                    if not self.instrument.wcdma_cell_on():
                        self._dump_recent_scpi("Cell ON 失败")
                        raise RuntimeError(f"WCDMA B{band}/{channel} Cell ON 失败；请查看前面的 SCPI 调试日志")
                    self._debug("Cell ON 成功，开始检查 CS/PS 建链状态")
                    if not self.instrument.wcdma_ensure_connected():
                        self._dump_recent_scpi("建链失败")
                        raise RuntimeError(f"WCDMA B{band}/{channel} 建链失败")
                    self._debug("WCDMA 建链成功", band=band, channel=channel)
                    for scene in self.config.scenes:
                        current += 1
                        self._cooperate()
                        from core.android_dut_control import apply_scene
                        apply_scene(self, scene)
                        self.set_state(TestState.MEASURING, f"WCDMA B{band}/{channel}/{scene} 灵敏度搜索")
                        result = search_wcdma_sensitivity(
                            start_level=self.config.initial_level,
                            max_step=self.config.max_step,
                            min_step=self.config.min_step,
                            threshold=self.config.ber_threshold,
                            fast_packet_count=self.config.fast_packet_count,
                            confirm_packet_count=self.config.packet_count,
                            set_level=self.instrument.wcdma_set_power,
                            ensure_connected=self.instrument.wcdma_ensure_connected,
                            measure_ber=self.instrument.wcdma_measure_ber,
                            cooperate=self._cooperate,
                        )
                        self.data_source = "SIMULATION" if isinstance(self.instrument, FakeCMW500) else "INSTRUMENT"
                        row = TestResult(index=current, mode="WCDMA", band=f"B{band}", channel=int(channel), channel_type="UARFCN", test_mode="RMC MODE1 PRBS9", rx_level=result.sensitivity, metric_type="BER", metric_value=result.ber, result="PASS", status="COMPLETED", run_id=self.run_id, data_source=self.data_source, global_cable_loss=self.config.cable_loss, total_loss=self.config.cable_loss, instrument_level=result.sensitivity, packet_count=self.config.packet_count, bler_threshold=self.config.ber_threshold, scan_phase=result.phase, scene=scene)
                        self.row_signal.emit(row)
                        self.summary_signal.emit({"run_id": self.run_id, "data_source": self.data_source, "scan_phase": result.phase, "attempt": result.measurements, "current_mode": "WCDMA", "current_band": f"B{band}", "current_channel": str(channel), "current_level": f"{result.sensitivity:g} dBm", "progress": f"{current}/{total}"})
                        self.log_signal.emit("INFO", f"WCDMA B{band} CH{channel} {scene} 灵敏度={result.sensitivity:g} dBm, BER={result.ber:g}")
                    if not self._safe_cell_off():
                        unsafe = True
                        raise RuntimeError("WCDMA Cell OFF 失败")
            outcome = TestState.COMPLETED
        except _StopRequested:
            outcome = TestState.STOPPED
        except Exception as exc:
            outcome = TestState.FAILED
            self.log_signal.emit("ERROR", f"WCDMA 测试流程异常：{exc}")
        finally:
            with QMutexLocker(self._mutex):
                self._cleanup_started = True
                self._paused = False
            try:
                from core.android_dut_control import cleanup_scene
                cleanup_scene(self)
            except Exception as exc:
                self.log_signal.emit("WARNING", f"DUT 场景清理异常：{exc}")
            cleanup_ok = self._safe_cell_off() if self._instrument_session_started else True
            try:
                if self._instrument_session_started:
                    self.instrument.disconnect()
            except Exception as exc:
                cleanup_ok = False
                self.log_signal.emit("ERROR", f"WCDMA 仪表断开异常：{exc}")
            final = TestState.FAILED_UNSAFE if unsafe or not cleanup_ok else (TestState.STOPPED if outcome is TestState.STOPPED else outcome)
            self.set_state(final, f"WCDMA 测试结束：{final.value}")
            self.run_metadata.status = final.value
            self.run_metadata.end_time = local_now_iso()
            self.finished_signal.emit()

    def _debug(self, message: str, **values: object) -> None:
        detail = ", ".join(f"{key}={value}" for key, value in values.items())
        self.log_signal.emit("DEBUG", f"[WCDMA-DEBUG] {message}" + (f" | {detail}" if detail else ""))

    def _dump_recent_scpi(self, reason: str, limit: int = 30) -> None:
        trace = getattr(self.instrument, "command_trace", None)
        if not isinstance(trace, list):
            return
        self.log_signal.emit("DEBUG", f"[WCDMA-DEBUG] {reason}，最近 SCPI 记录：")
        for item in trace[-limit:]:
            self.log_signal.emit("DEBUG", "[SCPI] stage={stage} op={operation} cmd={command} response={response!r} success={success} error={error}".format(**item))

    def _validate_config(self) -> None:
        if not self.config.selected_bands: raise ValueError("WCDMA Band 为空")
        if not self.config.scenes: raise ValueError("WCDMA 场景为空")
        if self.config.max_step < self.config.min_step: raise ValueError("WCDMA 最大步长不能小于最小步长")
        for value in (self.config.cable_loss, self.config.initial_level, self.config.connection_level, self.config.max_step, self.config.min_step, self.config.ber_threshold, self.config.power):
            if not math.isfinite(float(value)): raise ValueError("WCDMA 参数必须为有限数值")
        for band in self.config.selected_bands:
            if not self.config.channels_by_band.get(band): raise ValueError(f"WCDMA B{band} 未配置 UARFCN")

    def _prepare_instrument(self) -> None:
        clear = getattr(self.instrument, "clear_cancel", None)
        if clear: clear()
        checker = getattr(self.instrument, "set_cancel_checker", None)
        if checker: checker(self._is_stopped)
        if not self.instrument.is_connected(): self.instrument.connect()
        validate = getattr(self.instrument, "query_and_validate_idn", None)
        if callable(validate):
            self.run_metadata.instrument_idn = str(validate()).strip()
        self._instrument_session_started = True

    def _safe_cell_off(self) -> bool:
        try:
            method = getattr(self.instrument, "wcdma_cell_off", None)
            if method: method()
            return True
        except Exception as exc:
            self.log_signal.emit("ERROR", f"WCDMA Cell OFF 异常：{exc}")
            return False

    def set_state(self, state: TestState, message: str) -> None:
        self.current_state = state
        self.state_signal.emit(state.value)
        self.log_signal.emit("INFO", message)

    def pause(self) -> None:
        with QMutexLocker(self._mutex): self._paused = True
        self.set_state(TestState.PAUSED, "WCDMA 测试已暂停")

    def resume(self) -> None:
        with QMutexLocker(self._mutex): self._paused = False
        self.set_state(TestState.MEASURING, "WCDMA 测试继续")

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stopped = True
            self._paused = False
            cleanup_started = self._cleanup_started
        self.set_state(TestState.STOPPING, "WCDMA 请求停止测试")
        if not cleanup_started:
            cancel = getattr(self.instrument, "request_cancel", None)
            if cancel: cancel()

    def _is_stopped(self) -> bool:
        with QMutexLocker(self._mutex): return self._stopped

    def _raise_if_stopped(self) -> None:
        if self._is_stopped(): raise _StopRequested()

    def _cooperate(self) -> None:
        while True:
            with QMutexLocker(self._mutex): paused, stopped = self._paused, self._stopped
            if stopped: raise _StopRequested()
            if not paused: return
            import time
            time.sleep(0.05)

    def _interruptible_sleep(self, seconds: float) -> bool:
        import time
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            self._cooperate()
            time.sleep(min(0.05, deadline - time.monotonic()))
        return not self._is_stopped()
