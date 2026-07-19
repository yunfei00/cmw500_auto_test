from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable

from devices.instrument_transport import InstrumentCancelledError


class FakeCMW500:
    is_simulation = True
    data_source = "SIMULATION"

    def __init__(self) -> None:
        self.connected = False
        self.band = ""
        self.channel = 0
        self.rx_level = -70.0
        self.bw: float | None = None
        self.packet_count = 1000
        self.cable_loss = 0.0
        self._cancel_event = threading.Event()
        self._cancel_checker: Callable[[], bool] | None = None

    def connect(self) -> None:
        self.clear_cancel()
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def query_idn(self) -> str:
        return "Fake CMW500 Simulator"

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
        self._check_cancelled()
        self.band = band
        self.channel = channel
        self.bw = bw
        if packet_count is not None:
            self.packet_count = int(packet_count)
        if cable_loss is not None:
            self.cable_loss = float(cable_loss)
        time.sleep(0.02)

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
        self.setup_lte(
            band,
            channel,
            channel_type,
            test_mode,
            bw=bw,
            packet_count=packet_count,
            cable_loss=cable_loss,
        )

    def lte_cell_on(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        return None

    def wait_for_attach(self, timeout: float | None = None) -> bool:
        self._check_cancelled()
        return True

    def lte_before_measure(self) -> None:
        return None

    def set_rx_level(self, level: float) -> None:
        self._check_cancelled()
        self.rx_level = level
        time.sleep(0.01)

    def measure_bler(self, packet_count: int) -> float:
        self._check_cancelled()
        self.packet_count = int(packet_count)
        time.sleep(0.03)
        self._check_cancelled()
        dut_level = self.rx_level - self.cable_loss
        if dut_level >= -95:
            bler = random.uniform(0, 3)
        elif -105 <= dut_level < -95:
            bler = random.uniform(3, 12)
        else:
            bler = random.uniform(10, 40)
        return round(bler, 2)

    def lte_after_measure(self) -> None:
        return None

    def lte_cell_off(self) -> None:
        return None

    def lte_cleanup(self) -> None:
        return None

    def set_cancel_checker(self, checker: Callable[[], bool] | None) -> None:
        self._cancel_checker = checker

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def clear_cancel(self) -> None:
        self._cancel_event.clear()

    def abort_io(self) -> None:
        self.request_cancel()

    def _check_cancelled(self) -> None:
        callback_cancelled = (
            bool(self._cancel_checker()) if self._cancel_checker is not None else False
        )
        if self._cancel_event.is_set() or callback_cancelled:
            raise InstrumentCancelledError("模拟仪表操作已取消")
