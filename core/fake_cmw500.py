from __future__ import annotations

import random
import time


class FakeCMW500:
    def __init__(self) -> None:
        self.connected = False
        self.band = ""
        self.channel = 0
        self.rx_level = -70.0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def query_idn(self) -> str:
        return "Fake CMW500 Simulator"

    def setup_lte(self, band: str, channel: int) -> None:
        self.band = band
        self.channel = channel
        time.sleep(0.02)

    def lte_prepare_cell(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        self.setup_lte(band, channel)

    def lte_cell_on(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        return None

    def wait_for_attach(self, timeout: float | None = None) -> bool:
        return True

    def lte_before_measure(self) -> None:
        return None

    def set_rx_level(self, level: float) -> None:
        self.rx_level = level
        time.sleep(0.01)

    def measure_bler(self, packet_count: int) -> float:
        time.sleep(0.03)
        if self.rx_level >= -95:
            bler = random.uniform(0, 3)
        elif -105 <= self.rx_level < -95:
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
