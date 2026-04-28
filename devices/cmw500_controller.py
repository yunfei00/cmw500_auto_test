from __future__ import annotations

import random
import time

from core.scpi_template import ScpiTemplateManager
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
        self.scpi_template_manager: ScpiTemplateManager | None = None
        self.current_band = ""
        self.current_channel = 0
        self.current_channel_type = ""
        self.current_test_mode = ""
        self.current_rx_level = -70.0
        self.last_warning = ""
        self.last_commands: list[str] = []

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

    def set_scpi_template_manager(self, manager: ScpiTemplateManager | None) -> None:
        self.scpi_template_manager = manager

    def setup_lte(
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
        template = self._lte_template()
        if not template:
            self.last_warning = "未加载 SCPI 模板，setup_lte 仅保存状态"
            return

        context = self._build_context(
            band=band,
            channel=channel,
            channel_type=channel_type,
            test_mode=test_mode,
        )
        for raw_command in template.setup:
            command = self.scpi_template_manager.render_command(raw_command, context)
            self.write(command)
            self.last_commands.append(command)

    def set_rx_level(self, level: float) -> None:
        self.current_rx_level = level
        template = self._lte_template()
        if not template:
            self.last_warning = "未加载 SCPI 模板，set_rx_level 仅保存状态"
            return

        context = self._build_context(
            band=self.current_band,
            channel=self.current_channel,
            rx_level=level,
            channel_type=self.current_channel_type,
            test_mode=self.current_test_mode,
        )
        for raw_command in template.set_rx_level:
            command = self.scpi_template_manager.render_command(raw_command, context)
            self.write(command)
            self.last_commands.append(command)

    def measure_bler(self, packet_count: int) -> float:
        template = self._lte_template()
        if not template:
            if not self.fallback_simulation:
                raise RuntimeError("未加载 SCPI 模板，无法读取真实 BLER")
            self.last_warning = "未加载 SCPI 模板，RealCMW500 BLER 使用模拟值"
            return self._simulate_bler()

        measure_config = template.measure_bler
        context = self._build_context(
            band=self.current_band,
            channel=self.current_channel,
            rx_level=self.current_rx_level,
            packet_count=packet_count,
            channel_type=self.current_channel_type,
            test_mode=self.current_test_mode,
        )
        try:
            command = self.scpi_template_manager.render_command(measure_config.query, context)
            response = self.query(command)
            self.last_commands.append(command)
            return self.scpi_template_manager.parse_measure_response(
                response,
                measure_config.parser,
            )
        except Exception as exc:
            if self.fallback_simulation or measure_config.fallback_simulation:
                self.last_warning = f"真实 BLER 查询/解析失败，已使用模拟值：{exc}"
                return self._simulate_bler()
            raise

    def _build_context(
        self,
        band: str,
        channel: int,
        rx_level: float | None = None,
        packet_count: int | None = None,
        channel_type: str | None = None,
        test_mode: str | None = None,
    ) -> dict:
        band_number = str(band).lstrip("Bb")
        return {
            "mode": "LTE",
            "band": band,
            "band_number": band_number,
            "channel": channel,
            "channel_type": channel_type if channel_type is not None else self.current_channel_type,
            "rx_level": self.current_rx_level if rx_level is None else rx_level,
            "packet_count": "" if packet_count is None else packet_count,
            "test_mode": test_mode if test_mode is not None else self.current_test_mode,
        }

    def _simulate_bler(self) -> float:
        time.sleep(0.03)
        if self.current_rx_level >= -95:
            bler = random.uniform(0, 3)
        elif -105 <= self.current_rx_level < -95:
            bler = random.uniform(3, 12)
        else:
            bler = random.uniform(10, 40)
        return round(bler, 2)

    def _lte_template(self):
        if not self.scpi_template_manager:
            return None
        return self.scpi_template_manager.get_lte_template()
