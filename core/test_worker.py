from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QObject, QMutex, QMutexLocker, QTime, Signal

from core.channel_config import ChannelConfigManager
from core.fake_cmw500 import FakeCMW500
from core.models import LteTestConfig, TestItem, TestResult
from core.result_judge import judge_bler
from core.test_plan import generate_lte_test_plan
from core.test_states import TestState
from devices.instrument_base import InstrumentBase


class TestWorker(QObject):
    log_signal = Signal(str, str)
    row_signal = Signal(object)
    summary_signal = Signal(dict)
    finished_signal = Signal()
    state_signal = Signal(str)

    def __init__(
        self,
        config: LteTestConfig,
        channel_manager: ChannelConfigManager | None = None,
        instrument: InstrumentBase | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.channel_manager = channel_manager
        self.test_plan: list[TestItem] = []
        self.instrument = instrument or FakeCMW500()
        self.current_state = TestState.IDLE
        self.last_cell_key: tuple[str, int] | None = None
        self._paused = False
        self._stopped = False
        self._mutex = QMutex()

    def run(self) -> None:
        failed = False
        completed = False
        after_measure_needed = False

        try:
            self.set_state(TestState.PREPARING, "状态切换：PREPARING - 准备测试")
            instrument_type = self.instrument.__class__.__name__
            self.log_signal.emit("INFO", f"当前使用仪表类型：{instrument_type}")
            if not self._ensure_instrument_connected():
                failed = True
                self.set_state(TestState.FAILED, "状态切换：FAILED - 仪表连接失败")
                return

            self._log_real_instrument_template_state()
            self.log_signal.emit("INFO", "开始生成 LTE 测试计划")
            self.test_plan = generate_lte_test_plan(self.config, self.channel_manager)
            total = len(self.test_plan)
            self.log_signal.emit("INFO", f"共生成 {total} 条测试项")
            if total == 0:
                completed = True
                self.set_state(TestState.COMPLETED, "状态切换：COMPLETED - 没有测试项")
                return

            for current, item in enumerate(self.test_plan, start=1):
                if self._is_stopped():
                    self.log_signal.emit("INFO", "测试已收到停止请求，准备结束")
                    break

                self._wait_if_paused()
                if self._is_stopped():
                    self.log_signal.emit("INFO", "测试已收到停止请求，准备结束")
                    break

                if not self._ensure_cell_ready(item):
                    failed = True
                    break
                after_measure_needed = True

                self.set_state(TestState.MEASURING, "状态切换：MEASURING - 开始测量")
                if not self._measure_item(item, current, total):
                    failed = True
                    break

            if self._is_stopped():
                self.set_state(TestState.STOPPING, "状态切换：STOPPING - 测试停止中")
            elif failed:
                self.set_state(TestState.FAILED, "状态切换：FAILED - 测试失败")
            else:
                completed = True
        except Exception as exc:
            failed = True
            self.log_signal.emit("ERROR", f"测试流程异常：{exc}")
            self.set_state(TestState.FAILED, "状态切换：FAILED - 测试流程异常")
        finally:
            if after_measure_needed:
                try:
                    self._run_after_measure()
                except Exception as exc:
                    failed = True
                    self.log_signal.emit("ERROR", f"测量后处理异常：{exc}")
            self._safe_cell_off_and_cleanup()
            if completed and not failed and not self._is_stopped():
                self.set_state(TestState.COMPLETED, "状态切换：COMPLETED - 测试完成")
                self.log_signal.emit("INFO", "测试完成")
            elif self._is_stopped():
                self.log_signal.emit("INFO", "测试已停止")
            else:
                self.set_state(TestState.FAILED, "状态切换：FAILED - 测试失败")
                self.log_signal.emit("ERROR", "测试失败")
            self.finished_signal.emit()

    def set_state(self, state: TestState, message: str = "") -> None:
        self.current_state = state
        self.state_signal.emit(state.value)
        self.log_signal.emit("INFO", message or f"状态切换：{state.value}")

    def _ensure_instrument_connected(self) -> bool:
        try:
            if not self.instrument.is_connected():
                self.instrument.connect()
        except Exception as exc:
            self.log_signal.emit("ERROR", f"仪表连接失败，测试终止：{exc}")
            return False
        return True

    def _log_real_instrument_template_state(self) -> None:
        if self.instrument.__class__.__name__ != "RealCMW500":
            return
        manager = getattr(self.instrument, "scpi_template_manager", None)
        has_template = bool(manager and manager.has_template())
        self.log_signal.emit("INFO", f"RealCMW500 SCPI 模板已加载：{'是' if has_template else '否'}")
        if has_template:
            self.log_signal.emit("INFO", "使用 CMW500 SCPI 模板执行 LTE 测试流程")
        else:
            self.log_signal.emit(
                "WARNING",
                "未加载 SCPI 模板，RealCMW500 无法确认 UE Attach，测试将失败并执行清理",
            )

    def _ensure_cell_ready(self, item: TestItem) -> bool:
        cell_key = (item.band, item.channel)
        if self.last_cell_key == cell_key:
            return True

        if self.last_cell_key is not None:
            self._safe_cell_off()

        self.set_state(
            TestState.CELL_CONFIGURING,
            f"状态切换：CELL_CONFIGURING - 开始配置 LTE 小区 {item.band}/{item.channel}",
        )
        try:
            self._call_lte_prepare_cell(item)
            self._emit_instrument_warning()
            self.log_signal.emit("INFO", f"开始配置 LTE 小区：{item.band} 信道 {item.channel}")

            self.set_state(TestState.CELL_ON, "状态切换：CELL_ON - LTE Cell ON")
            self._call_lte_cell_on(item)
            self._emit_instrument_warning()
            self.log_signal.emit("INFO", "LTE Cell ON")

            self.set_state(TestState.WAITING_ATTACH, "状态切换：WAITING_ATTACH - 开始等待 UE Attach")
            self.log_signal.emit("INFO", "开始等待 UE Attach")
            if not self._call_wait_for_attach():
                self._emit_instrument_warning()
                self.log_signal.emit("ERROR", "Attach 失败/超时")
                return False

            self._emit_instrument_warning()
            self.set_state(TestState.ATTACHED, "状态切换：ATTACHED - Attach 成功")
            self.log_signal.emit("INFO", "Attach 成功")
            self._run_before_measure()
            self.last_cell_key = cell_key
            return True
        except Exception as exc:
            self._emit_instrument_warning()
            self.log_signal.emit("ERROR", f"LTE 小区准备异常：{exc}")
            return False

    def _measure_item(self, item: TestItem, current: int, total: int) -> bool:
        try:
            self.log_signal.emit(
                "INFO",
                f"当前 Band/Channel/RxLevel：{item.band}/{item.channel}/{item.rx_level:g} dBm",
            )
            self.instrument.set_rx_level(item.rx_level)
            self._emit_instrument_warning()
            time.sleep(min(max(self.config.settle_time, 0), 0.2))
            bler = self.instrument.measure_bler(self.config.packet_count)
            self._emit_instrument_warning()
            self.log_signal.emit("INFO", f"BLER 解析值：{bler:.2f}%")
            result = judge_bler(bler, self.config.bler_threshold)
            status = "已完成"
        except Exception as exc:
            bler = 0.0
            result = "FAIL"
            status = "异常"
            self.log_signal.emit("ERROR", f"测试项 {item.index} 执行异常：{exc}")
            test_result = self._build_result(item, bler, result, status)
            self.row_signal.emit(test_result)
            self._emit_summary(item, current, total)
            return False

        test_result = self._build_result(item, bler, result, status)
        self.row_signal.emit(test_result)
        self._emit_summary(item, current, total)
        self.log_signal.emit(
            "INFO",
            f"LTE {item.band} 信道 {item.channel} 电平 {item.rx_level:g} dBm BLER={bler:.2f}% {result}",
        )
        return True

    def _run_before_measure(self) -> None:
        self.log_signal.emit("INFO", "执行测量前命令")
        self._call_optional("lte_before_measure")
        self._emit_instrument_warning()

    def _run_after_measure(self) -> None:
        self.log_signal.emit("INFO", "执行测量后命令")
        self._call_optional("lte_after_measure")
        self._emit_instrument_warning()

    def _safe_cell_off_and_cleanup(self) -> None:
        self.set_state(TestState.CLEANUP, "状态切换：CLEANUP - 清理测试环境")
        self._safe_cell_off()
        self._safe_cleanup()

    def _safe_cell_off(self) -> None:
        try:
            self.log_signal.emit("INFO", "Cell OFF")
            self._call_optional("lte_cell_off")
            self._emit_instrument_warning()
        except Exception as exc:
            self.log_signal.emit("ERROR", f"Cell OFF 异常：{exc}")

    def _safe_cleanup(self) -> None:
        try:
            self.log_signal.emit("INFO", "Cleanup")
            self._call_optional("lte_cleanup")
            self._emit_instrument_warning()
        except Exception as exc:
            self.log_signal.emit("ERROR", f"Cleanup 异常：{exc}")

    def _call_lte_prepare_cell(self, item: TestItem) -> None:
        method = getattr(self.instrument, "lte_prepare_cell", None)
        if method:
            method(item.band, item.channel, item.channel_type, item.test_mode)
            return
        self._setup_lte_compat(item)

    def _call_lte_cell_on(self, item: TestItem) -> None:
        method = getattr(self.instrument, "lte_cell_on", None)
        if method:
            method(item.band, item.channel, item.channel_type, item.test_mode)

    def _call_wait_for_attach(self) -> bool:
        method = getattr(self.instrument, "wait_for_attach", None)
        if method:
            return bool(method())
        return True

    def _call_optional(self, method_name: str) -> Any:
        method = getattr(self.instrument, method_name, None)
        if method:
            return method()
        return None

    def _setup_lte_compat(self, item: TestItem) -> None:
        try:
            self.instrument.setup_lte(
                item.band,
                item.channel,
                channel_type=item.channel_type,
                test_mode=item.test_mode,
            )
        except TypeError:
            self.instrument.setup_lte(item.band, item.channel)

    def _emit_instrument_warning(self) -> None:
        warning = getattr(self.instrument, "last_warning", "")
        if warning:
            self.log_signal.emit("WARNING", warning)
            try:
                self.instrument.last_warning = ""
            except Exception:
                pass

    def _emit_summary(self, item: TestItem, current: int, total: int) -> None:
        self.summary_signal.emit(
            {
                "current_mode": "LTE",
                "current_band": item.band,
                "current_channel": str(item.channel),
                "current_level": f"{item.rx_level:g} dBm",
                "progress": f"{current}/{total}",
            }
        )

    def _build_result(self, item: TestItem, bler: float, result: str, status: str) -> TestResult:
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
            timestamp=QTime.currentTime().toString("HH:mm:ss"),
        )

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
            self._stopped = True
            self._paused = False
        self.set_state(TestState.STOPPING, "状态切换：STOPPING - 请求停止测试")

    def _is_stopped(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stopped

    def _is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._paused

    def _wait_if_paused(self) -> None:
        while self._is_paused() and not self._is_stopped():
            time.sleep(0.05)
