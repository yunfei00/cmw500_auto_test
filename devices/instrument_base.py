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

    def set_rx_level(self, level: float) -> None:
        raise NotImplementedError

    def measure_bler(self, packet_count: int) -> float:
        raise NotImplementedError
