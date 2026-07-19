from __future__ import annotations

from collections.abc import Callable


class InstrumentBase:
    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError

    def query_idn(self) -> str:
        raise NotImplementedError

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
        raise NotImplementedError

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

    def set_cancel_checker(self, checker: Callable[[], bool] | None) -> None:
        """Set a cooperative cancellation callback for blocking operations."""

    def request_cancel(self) -> None:
        """Request cancellation of the current operation."""

    def clear_cancel(self) -> None:
        """Clear a previous cancellation request before starting a new run."""

    def abort_io(self) -> None:
        """Abort pending I/O. Implementations may close the connection."""

        self.request_cancel()
