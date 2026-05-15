from __future__ import annotations

import random
import time

from core.scpi_template import ScpiTemplateManager
from devices.instrument_base import InstrumentBase
from devices.instrument_transport import InstrumentTransport, SocketTransport


class RealCMW500(InstrumentBase):
    def __init__(
        self,
        transport: InstrumentTransport,
        fallback_simulation: bool = True,
    ) -> None:
        self.transport = transport
        self.fallback_simulation = fallback_simulation
        self.scpi_template_manager: ScpiTemplateManager | None = None
        self.current_band = ""
        self.current_channel = 0
        self.current_channel_type = ""
        self.current_test_mode = ""
        self.current_rx_level = -70.0
        self.last_warning = ""
        self.last_attach_response = ""
        self.last_commands: list[str] = []

    def connect(self) -> None:
        self.transport.connect()

    def disconnect(self) -> None:
        self.transport.close()

    def is_connected(self) -> bool:
        return self.transport.is_connected()

    def query_idn(self) -> str:
        return self.query("*IDN?")

    def write(self, command: str) -> None:
        self.transport.write(command)

    def query(self, command: str) -> str:
        return self.transport.query(command)


    @classmethod
    def from_socket(
        cls,
        host: str,
        port: int = 5025,
        timeout_ms: int = 10000,
        fallback_simulation: bool = True,
    ) -> "RealCMW500":
        return cls(SocketTransport(host, port, timeout_ms), fallback_simulation=fallback_simulation)
    def reset(self) -> None:
        self.write("*RST")

    def preset(self) -> None:
        self.write("SYST:PRES")

    def set_scpi_template_manager(self, manager: ScpiTemplateManager | None) -> None:
        self.scpi_template_manager = manager

    def execute_template_commands(
        self,
        commands: list[str],
        context: dict,
        stage: str = "",
    ) -> None:
        if not commands:
            return
        if not self.scpi_template_manager:
            raise RuntimeError("未加载 SCPI 模板管理器")

        for raw_command in commands:
            command = self.scpi_template_manager.render_command(raw_command, context)
            try:
                self.write(command)
                self.last_commands.append(command)
            except Exception as exc:
                stage_text = f"{stage} " if stage else ""
                raise RuntimeError(f"{stage_text}SCPI 命令执行失败：{command}，{exc}") from exc

    def lte_prepare_cell(
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
            self.last_warning = "未加载 LTE SCPI 模板，lte_prepare_cell 未发送真实命令"
            return

        self.execute_template_commands(
            template.setup,
            self._build_context(
                band=band,
                channel=channel,
                channel_type=channel_type,
                test_mode=test_mode,
            ),
            "lte_prepare_cell",
        )

    def lte_cell_on(
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
            self.last_warning = "未加载 LTE SCPI 模板，lte_cell_on 未发送真实命令"
            return
        if not template.cell_on:
            self.last_warning = "LTE SCPI 模板未配置 cell_on，已跳过 Cell ON"
            return

        self.execute_template_commands(
            template.cell_on,
            self._build_context(
                band=band,
                channel=channel,
                channel_type=channel_type,
                test_mode=test_mode,
            ),
            "lte_cell_on",
        )

    def wait_for_attach(self, timeout: float | None = None) -> bool:
        template = self._lte_template()
        if not template or not template.wait_attach:
            self.last_warning = "未配置 wait_attach 模板，无法确认 UE Attach 状态"
            return False
        if not self.scpi_template_manager:
            self.last_warning = "未加载 SCPI 模板管理器，无法等待 UE Attach"
            return False

        wait_config = template.wait_attach
        timeout_sec = timeout if timeout is not None else wait_config.timeout_sec
        timeout_sec = max(float(timeout_sec), 0.0)
        interval_sec = max(float(wait_config.interval_sec), 0.05)
        deadline = time.monotonic() + timeout_sec
        context = self._build_context(
            band=self.current_band,
            channel=self.current_channel,
            rx_level=self.current_rx_level,
            channel_type=self.current_channel_type,
            test_mode=self.current_test_mode,
        )

        while True:
            try:
                command = self.scpi_template_manager.render_command(wait_config.query, context)
                response = self.query(command)
                self.last_commands.append(command)
                self.last_attach_response = response
                if self.scpi_template_manager.parse_wait_response(
                    response,
                    wait_config.parser,
                    wait_config.expected,
                ):
                    return True
            except Exception as exc:
                self.last_warning = f"wait_attach 查询异常：{exc}"
                if wait_config.fallback_success:
                    self.last_warning = f"{self.last_warning}，已按 fallback_success 继续"
                    return True

            if time.monotonic() >= deadline:
                break
            time.sleep(min(interval_sec, max(deadline - time.monotonic(), 0.0)))

        if wait_config.fallback_success:
            self.last_warning = "wait_attach 超时，已按 fallback_success 继续"
            return True
        self.last_warning = f"wait_attach 超时，最后响应：{self.last_attach_response or '-'}"
        return False

    def lte_before_measure(self) -> None:
        template = self._lte_template()
        if not template:
            return
        self.execute_template_commands(
            template.before_measure,
            self._build_context(self.current_band, self.current_channel),
            "lte_before_measure",
        )

    def lte_after_measure(self) -> None:
        template = self._lte_template()
        if not template:
            return
        self.execute_template_commands(
            template.after_measure,
            self._build_context(self.current_band, self.current_channel),
            "lte_after_measure",
        )

    def lte_cell_off(self) -> None:
        template = self._lte_template()
        if not template:
            self.last_warning = "未加载 LTE SCPI 模板，lte_cell_off 未发送真实命令"
            return
        if not template.cell_off:
            self.last_warning = "LTE SCPI 模板未配置 cell_off，已跳过 Cell OFF"
            return
        self.execute_template_commands(
            template.cell_off,
            self._build_context(self.current_band, self.current_channel),
            "lte_cell_off",
        )

    def lte_cleanup(self) -> None:
        template = self._lte_template()
        if not template:
            return
        try:
            self.execute_template_commands(
                template.cleanup,
                self._build_context(self.current_band, self.current_channel),
                "lte_cleanup",
            )
        except Exception as exc:
            self.last_warning = f"Cleanup 执行异常，已忽略：{exc}"

    def setup_lte(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        self.lte_prepare_cell(band, channel, channel_type, test_mode)

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
        self.execute_template_commands(template.set_rx_level, context, "set_rx_level")

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
