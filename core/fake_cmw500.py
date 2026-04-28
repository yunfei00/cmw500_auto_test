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
