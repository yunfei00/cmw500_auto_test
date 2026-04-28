from __future__ import annotations

import random
import time

from devices.instrument_base import InstrumentBase
from devices.scpi_socket_client import ScpiSocketClient


class RealCMW500(InstrumentBase):
    def __init__(
        self,
        host: str,
        port: int = 5025,
        timeout: float = 5.0,
        fallback_simulation: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.fallback_simulation = fallback_simulation
        self.client = ScpiSocketClient(host, port, timeout)
        self.current_band = ""
        self.current_channel = 0
        self.current_rx_level = -70.0
        self.last_warning = ""

    def connect(self) -> None:
        self.client.connect()

    def disconnect(self) -> None:
        self.client.disconnect()

    def is_connected(self) -> bool:
        return self.client.is_connected()

    def query_idn(self) -> str:
        return self.query("*IDN?")

    def write(self, command: str) -> None:
        self.client.write(command)

    def query(self, command: str) -> str:
        return self.client.query(command)

    def reset(self) -> None:
        self.write("*RST")

    def preset(self) -> None:
        self.write("SYST:PRES")

    def setup_lte(self, band: str, channel: int) -> None:
        # TODO: 补充真实 CMW500 LTE 小区配置 SCPI 命令。
        self.current_band = band
        self.current_channel = channel

    def set_rx_level(self, level: float) -> None:
        # TODO: 补充真实 CMW500 RX Level 设置 SCPI 命令。
        self.current_rx_level = level

    def measure_bler(self, packet_count: int) -> float:
        # TODO: 补充真实 CMW500 LTE BLER 读取 SCPI 命令。
        if not self.fallback_simulation:
            raise RuntimeError("RealCMW500.measure_bler 尚未配置真实 SCPI 命令")

        self.last_warning = "当前 RealCMW500 BLER 为模拟值，真实测量命令尚未配置"
        time.sleep(0.03)
        if self.current_rx_level >= -95:
            bler = random.uniform(0, 3)
        elif -105 <= self.current_rx_level < -95:
            bler = random.uniform(3, 12)
        else:
            bler = random.uniform(10, 40)
        return round(bler, 2)
