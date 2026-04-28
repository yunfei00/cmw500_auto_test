from __future__ import annotations


class InstrumentBase:
    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError

    def query_idn(self) -> str:
        raise NotImplementedError

    def setup_lte(self, band: str, channel: int) -> None:
        raise NotImplementedError

    def lte_prepare_cell(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        raise NotImplementedError

    def lte_cell_on(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
    ) -> None:
        raise NotImplementedError

    def wait_for_attach(self, timeout: float | None = None) -> bool:
        raise NotImplementedError

    def lte_before_measure(self) -> None:
        raise NotImplementedError

    def set_rx_level(self, level: float) -> None:
        raise NotImplementedError

    def measure_bler(self, packet_count: int) -> float:
        raise NotImplementedError

    def lte_after_measure(self) -> None:
        raise NotImplementedError

    def lte_cell_off(self) -> None:
        raise NotImplementedError

    def lte_cleanup(self) -> None:
        raise NotImplementedError
