from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from core.fake_cmw500 import FakeCMW500
from core.models import LteTestConfig
from core.test_states import TestState as WorkerState
from core.test_worker import TestWorker as Worker


class PlanManager:
    def has_config(self) -> bool:
        return True

    def get_band_config(self, band: str) -> SimpleNamespace:
        return SimpleNamespace(loss_db=2.0)


class SequenceInstrument:
    data_source = "INSTRUMENT"

    def __init__(self, responses: dict[float, list[float | Exception]]) -> None:
        self.connected = False
        self.responses = {level: list(values) for level, values in responses.items()}
        self.levels: list[float] = []
        self.prepares: list[dict[str, object]] = []
        self.current_level = 0.0
        self.cancel_requests = 0
        self.abort_requests = 0
        self.disconnect_count = 0

    def connect(self) -> None:
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    def disconnect(self) -> None:
        self.connected = False
        self.disconnect_count += 1

    def lte_prepare_cell(
        self,
        band: str,
        channel: int,
        channel_type: str = "",
        test_mode: str = "",
        bw: float | None = None,
        packet_count: int | None = None,
    ) -> None:
        self.prepares.append(
            {
                "band": band,
                "channel": channel,
                "channel_type": channel_type,
                "test_mode": test_mode,
                "bw": bw,
                "packet_count": packet_count,
            }
        )

    def lte_cell_on(self, *args: object, **kwargs: object) -> None:
        return None

    def wait_for_attach(self, cancel_check=None) -> bool:
        return not (cancel_check and cancel_check())

    def lte_before_measure(self) -> None:
        return None

    def lte_after_measure(self) -> None:
        return None

    def set_rx_level(self, level: float) -> None:
        self.current_level = level
        self.levels.append(level)

    def measure_bler(self, packet_count: int) -> float:
        dut_level = round(self.current_level - 3.0, 10)
        response = self.responses[dut_level].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def lte_cell_off(self) -> None:
        return None

    def lte_cleanup(self) -> None:
        return None

    def request_cancel(self) -> None:
        self.cancel_requests += 1

    def abort_io(self) -> None:
        self.abort_requests += 1


def sample_config(**overrides: object) -> LteTestConfig:
    values: dict[str, object] = {
        "cable_loss": 1.0,
        "sensitivity_upper": -85.0,
        "start_level": -80.0,
        "stop_level": -90.0,
        "packet_count": 1000,
        "max_step": 4.0,
        "min_step": 1.0,
        "bler_threshold": 10.0,
        "settle_time": 0,
        "retry_count": 1,
        "selected_bands": ["B3"],
        "selected_channel_types": [],
        "custom_channels": [],
        "lte_test_items": ["转盘测试"],
        "test_mode": "单主",
        "data": [
            {
                "band": "B3",
                "channel": 1575,
                "bw": 20,
                "loss_db": 2.0,
                "desc": "转盘测试",
            }
        ],
        "run_id": "run-001",
    }
    values.update(overrides)
    return LteTestConfig(**values)


def test_worker_coarse_and_fine_scan_retries_and_traceability() -> None:
    instrument = SequenceInstrument(
        {
            -80.0: [1.0],
            -84.0: [2.0],
            -88.0: [20.0, 21.0],
            -85.0: [3.0],
            -86.0: [12.0, 4.0],
            -87.0: [15.0, 16.0],
        }
    )
    worker = Worker(sample_config(), PlanManager(), instrument)
    rows = []
    states: list[str] = []
    worker.row_signal.connect(rows.append)
    worker.state_signal.connect(states.append)

    worker.run()

    assert worker.current_state is WorkerState.COMPLETED
    assert states[-1] == "COMPLETED"
    assert instrument.prepares == [
        {
            "band": "B3",
            "channel": 1575,
            "channel_type": "转盘测试",
            "test_mode": "单主",
            "bw": 20.0,
            "packet_count": 1000,
        }
    ]
    assert [(row.scan_phase, row.rx_level, row.attempt, row.result) for row in rows] == [
        ("COARSE", -80.0, 1, "PASS"),
        ("COARSE", -84.0, 1, "PASS"),
        ("COARSE", -88.0, 1, "FAIL"),
        ("COARSE", -88.0, 2, "FAIL"),
        ("FINE", -85.0, 1, "PASS"),
        ("FINE", -86.0, 1, "FAIL"),
        ("FINE", -86.0, 2, "PASS"),
        ("FINE", -87.0, 1, "FAIL"),
        ("FINE", -87.0, 2, "FAIL"),
    ]
    assert instrument.levels == [row.rx_level + 3.0 for row in rows]
    assert all(row.run_id == "run-001" for row in rows)
    assert all(row.data_source == "REAL" for row in rows)
    assert all(row.bw == 20.0 for row in rows)
    assert all(row.global_cable_loss == 1.0 for row in rows)
    assert all(row.channel_loss == 2.0 for row in rows)
    assert all(row.total_loss == 3.0 for row in rows)
    assert all(row.packet_count == 1000 for row in rows)
    assert all(row.bler_threshold == 10.0 for row in rows)
    assert all(row.sensitivity_upper == -85.0 for row in rows)
    assert all(datetime.fromisoformat(row.timestamp).tzinfo is not None for row in rows)
    assert instrument.disconnect_count == 1
    assert not instrument.connected


def test_invalid_bler_is_retried_and_each_attempt_is_retained() -> None:
    config = sample_config(start_level=-80.0, stop_level=-81.0)
    instrument = SequenceInstrument(
        {-80.0: [float("nan"), 2.0], -81.0: [20.0, 21.0]}
    )
    worker = Worker(config, PlanManager(), instrument)
    rows = []
    worker.row_signal.connect(rows.append)

    worker.run()

    assert worker.current_state is WorkerState.COMPLETED
    assert [row.result for row in rows[:2]] == ["ERROR", "PASS"]
    assert rows[0].metric_value is None
    assert "finite" in rows[0].error_message
    assert rows[0].status == "RETRY_PENDING"
    assert rows[1].attempt == 2


def test_cleanup_failure_sets_failed_unsafe() -> None:
    class UnsafeInstrument(SequenceInstrument):
        def lte_cleanup(self) -> None:
            raise RuntimeError("cleanup failed")

    config = sample_config(start_level=-80.0, stop_level=-81.0)
    worker = Worker(
        config,
        PlanManager(),
        UnsafeInstrument({-80.0: [1.0], -81.0: [1.0]}),
    )

    worker.run()

    assert worker.current_state is WorkerState.FAILED_UNSAFE
    assert worker.run_metadata.status == "FAILED_UNSAFE"
    assert worker.run_metadata.end_time


def test_stop_requests_instrument_cancel_and_finishes_stopped() -> None:
    instrument = SequenceInstrument({-80.0: [1.0]})
    worker = Worker(
        sample_config(start_level=-80.0, stop_level=-81.0),
        PlanManager(),
        instrument,
    )

    worker.stop()
    worker.stop()
    worker.run()

    assert instrument.cancel_requests == 1
    assert instrument.abort_requests == 1
    assert worker.current_state is WorkerState.STOPPED


def test_stop_reconnects_after_abort_before_safe_cleanup() -> None:
    class ClosingInstrument(SequenceInstrument):
        def __init__(self) -> None:
            super().__init__({-80.0: [1.0]})
            self.worker: Worker | None = None
            self.connect_count = 0
            self.cell_off_count = 0

        def connect(self) -> None:
            super().connect()
            self.connect_count += 1

        def measure_bler(self, packet_count: int) -> float:
            assert self.worker is not None
            self.worker.stop()
            return 1.0

        def abort_io(self) -> None:
            super().abort_io()
            self.connected = False

        def lte_cell_off(self) -> None:
            assert self.connected
            self.cell_off_count += 1

    instrument = ClosingInstrument()
    worker = Worker(sample_config(), PlanManager(), instrument)
    instrument.worker = worker

    worker.run()

    assert worker.current_state is WorkerState.STOPPED
    assert instrument.connect_count == 2
    assert instrument.cell_off_count == 1


def test_stop_during_cleanup_does_not_abort_safety_commands() -> None:
    class StopInAfterMeasureInstrument(SequenceInstrument):
        def __init__(self) -> None:
            super().__init__({-80.0: [1.0], -81.0: [1.0]})
            self.worker: Worker | None = None

        def lte_after_measure(self) -> None:
            assert self.worker is not None
            self.worker.stop()

    instrument = StopInAfterMeasureInstrument()
    worker = Worker(
        sample_config(start_level=-80.0, stop_level=-81.0),
        PlanManager(),
        instrument,
    )
    instrument.worker = worker

    worker.run()

    assert worker.current_state is WorkerState.STOPPED
    assert instrument.cancel_requests == 0
    assert instrument.abort_requests == 0


def test_worker_rejects_invalid_scan_steps() -> None:
    instrument = SequenceInstrument({-80.0: [1.0]})
    worker = Worker(sample_config(max_step=0.5, min_step=1.0), PlanManager(), instrument)

    worker.run()

    assert worker.current_state is WorkerState.FAILED

    negative_loss_worker = Worker(
        sample_config(cable_loss=-0.1),
        PlanManager(),
        SequenceInstrument({-80.0: [1.0]}),
    )
    negative_loss_worker.run()
    assert negative_loss_worker.current_state is WorkerState.FAILED


def test_worker_rejects_empty_plan_instead_of_reporting_completed() -> None:
    class EmptyManager:
        def has_config(self) -> bool:
            return False

    worker = Worker(sample_config(data=[]), EmptyManager(), SequenceInstrument({}))

    worker.run()

    assert worker.current_state is WorkerState.FAILED


def test_worker_rejects_non_finite_channel_loss_before_rf_setup() -> None:
    config = sample_config()
    config.data[0]["loss_db"] = float("nan")
    instrument = SequenceInstrument({})
    worker = Worker(config, PlanManager(), instrument)

    worker.run()

    assert worker.current_state is WorkerState.FAILED
    assert instrument.prepares == []


def test_fake_instrument_applies_path_loss_before_simulating_bler() -> None:
    instrument = FakeCMW500()
    instrument.connect()
    instrument.lte_prepare_cell("B3", 1575, cable_loss=3.0)
    instrument.set_rx_level(-97.0)

    with patch("core.fake_cmw500.random.uniform", return_value=5.0) as uniform:
        assert instrument.measure_bler(1000) == 5.0

    uniform.assert_called_once_with(3, 12)
