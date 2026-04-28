from __future__ import annotations

import time

from PySide6.QtCore import QObject, QMutex, QMutexLocker, QTime, Signal

from core.channel_config import ChannelConfigManager
from core.fake_cmw500 import FakeCMW500
from core.models import LteTestConfig, TestResult
from core.result_judge import judge_bler
from core.test_plan import generate_lte_test_plan
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
        self.test_plan = []
        self.instrument = instrument or FakeCMW500()
        self._paused = False
        self._stopped = False
        self._mutex = QMutex()

    def run(self) -> None:
        self.state_signal.emit("running")
        instrument_type = self.instrument.__class__.__name__
        self.log_signal.emit("INFO", f"当前仪表类型：{instrument_type}")
        if not self._ensure_instrument_connected():
            self.state_signal.emit("finished")
            self.finished_signal.emit()
            return

        self._log_real_instrument_template_state()

        self.log_signal.emit("INFO", "开始生成 LTE 测试计划")
        self.test_plan = generate_lte_test_plan(self.config, self.channel_manager)
        total = len(self.test_plan)
        self.log_signal.emit("INFO", f"共生成 {total} 条测试项")

        try:
            for current, item in enumerate(self.test_plan, start=1):
                if self._is_stopped():
                    self.log_signal.emit("INFO", "测试已收到停止请求，准备结束")
                    break

                self._wait_if_paused()
                if self._is_stopped():
                    self.log_signal.emit("INFO", "测试已收到停止请求，准备结束")
                    break

                try:
                    self._setup_lte(item)
                    self.instrument.set_rx_level(item.rx_level)
                    time.sleep(min(max(self.config.settle_time, 0), 0.2))
                    bler = self.instrument.measure_bler(self.config.packet_count)
                    self._emit_instrument_warning()
                    result = judge_bler(bler, self.config.bler_threshold)
                    status = "已完成"
                except Exception as exc:
                    bler = 0.0
                    result = "FAIL"
                    status = "异常"
                    self.log_signal.emit("ERROR", f"测试项 {item.index} 执行异常：{exc}")

                test_result = self._build_result(
                    item=item,
                    bler=bler,
                    result=result,
                    status=status,
                )

                self.row_signal.emit(test_result)
                self.summary_signal.emit(
                    {
                        "current_mode": "LTE",
                        "current_band": item.band,
                        "current_channel": str(item.channel),
                        "current_level": f"{item.rx_level:g} dBm",
                        "progress": f"{current}/{total}",
                    }
                )
                self.log_signal.emit(
                    "INFO",
                    f"LTE {item.band} 信道 {item.channel} 电平 {item.rx_level:g} dBm BLER={bler:.2f}% {result}",
                )
        finally:
            self.state_signal.emit("finished")
            self.finished_signal.emit()

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
            self.log_signal.emit("INFO", "使用 CMW500 SCPI 模板执行 LTE 测试")
        else:
            self.log_signal.emit("WARNING", "未加载 SCPI 模板，BLER 将使用模拟值")

    def _setup_lte(self, item) -> None:
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

    def _build_result(self, item, bler: float, result: str, status: str) -> TestResult:
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
        self.state_signal.emit("paused")

    def resume(self) -> None:
        with QMutexLocker(self._mutex):
            self._paused = False
        self.state_signal.emit("running")

    def stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stopped = True
            self._paused = False
        self.state_signal.emit("stopping")

    def _is_stopped(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._stopped

    def _is_paused(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._paused

    def _wait_if_paused(self) -> None:
        while self._is_paused() and not self._is_stopped():
            time.sleep(0.05)
