from __future__ import annotations

import time

from PySide6.QtCore import QObject, QMutex, QMutexLocker, QTime, Signal

from core.channel_config import ChannelConfigManager
from core.fake_cmw500 import FakeCMW500
from core.models import LteTestConfig, TestResult
from core.result_judge import judge_bler
from core.test_plan import generate_lte_test_plan


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
    ) -> None:
        super().__init__()
        self.config = config
        self.channel_manager = channel_manager
        self.test_plan = []
        self.cmw500 = FakeCMW500()
        self._paused = False
        self._stopped = False
        self._mutex = QMutex()

    def run(self) -> None:
        self.state_signal.emit("running")
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

                self.cmw500.setup_lte(item.band, item.channel)
                self.cmw500.set_rx_level(item.rx_level)
                time.sleep(min(max(self.config.settle_time, 0), 0.2))
                bler = self.cmw500.measure_bler(self.config.packet_count)
                result = judge_bler(bler, self.config.bler_threshold)

                test_result = TestResult(
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
                    status="已完成",
                    timestamp=QTime.currentTime().toString("HH:mm:ss"),
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
