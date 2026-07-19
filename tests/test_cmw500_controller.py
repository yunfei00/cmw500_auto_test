from __future__ import annotations

import json
from collections import defaultdict

import pytest

from core.scpi_template import ScpiTemplateManager
from devices.cmw500_controller import (
    RealCMW500,
    is_cmw500_idn,
    validate_cmw500_idn,
)
from devices.instrument_transport import InstrumentTransport


class ScriptedTransport(InstrumentTransport):
    def __init__(self, responses: dict[str, list[str]] | None = None) -> None:
        self.connected = False
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.responses: defaultdict[str, list[str]] = defaultdict(list)
        for command, values in (responses or {}).items():
            self.responses[command].extend(values)

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.connected = False

    def write(self, command: str) -> None:
        if not self.connected:
            raise RuntimeError("disconnected")
        self.writes.append(command)

    def query(self, command: str) -> str:
        if not self.connected:
            raise RuntimeError("disconnected")
        self.queries.append(command)
        values = self.responses[command]
        if not values:
            raise RuntimeError(f"no response for {command}")
        return values.pop(0)

    def is_connected(self) -> bool:
        return self.connected


def _manager(tmp_path, **measure_overrides) -> ScpiTemplateManager:
    measure = {
        "start": ["INIT:BLER"],
        "state_query": "FETC:BLER:STATE?",
        "state_parser": "equals",
        "state_done": "RDY",
        "state_interval_sec": 0.001,
        "state_timeout_sec": 0.2,
        "query": "FETC:BLER?",
        "parser": "first_float",
        "stop": ["STOP:BLER"],
        "fallback_simulation": True,
    }
    measure.update(measure_overrides)
    path = tmp_path / "controller_template.json"
    path.write_text(
        json.dumps(
            {
                "lte": {
                    "setup": [
                        "INST LTE",
                        "CONF:BAND {band_number}",
                        "CONF:BW {bw}",
                        "CONF:PACKETS {packet_count}",
                        "CONF:LOSS {cable_loss}",
                        "CONF:FREQ?",
                    ],
                    "cell_on": ["CELL ON"],
                    "wait_attach": {
                        "query": "RRC?",
                        "parser": "contains",
                        "expected": "CONN",
                        "interval_sec": 0.001,
                        "timeout_sec": 0.2,
                        "fallback_success": True,
                    },
                    "set_rx_level": ["CONF:RX {rx_level}"],
                    "measure_bler": measure,
                    "cell_off": ["CELL OFF"],
                    "cleanup": [
                        {
                            "type": "query_and_assert",
                            "command": "SYST:ERR?",
                            "parser": "regex",
                            "expected": r"^0(?:,|$)",
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    manager = ScpiTemplateManager()
    manager.load_file(str(path))
    return manager


def _controller(tmp_path, responses, **measure_overrides):
    transport = ScriptedTransport(responses)
    controller = RealCMW500(transport, fallback_simulation=True)
    controller.set_scpi_template_manager(_manager(tmp_path, **measure_overrides))
    controller.connect()
    return controller, transport


def test_setup_consumes_legacy_query_and_records_structured_trace(tmp_path) -> None:
    controller, transport = _controller(tmp_path, {"CONF:FREQ?": ["1805E6"]})

    controller.lte_prepare_cell(
        "B3", 1300, bw=10, packet_count=2048, cable_loss=1.5
    )

    assert "CONF:BW 10" in transport.writes
    assert "CONF:PACKETS 2048" in transport.writes
    assert "CONF:LOSS 1.5" in transport.writes
    assert transport.queries == ["CONF:FREQ?"]
    query_trace = controller.command_trace[-1]
    assert query_trace["operation"] == "query"
    assert query_trace["response"] == "1805E6"
    assert query_trace["success"] is True


def test_attach_and_measure_state_do_not_accept_unsafe_substrings(tmp_path) -> None:
    responses = {
        "CONF:FREQ?": ["1805E6"],
        "RRC?": ["DISCONN", "CONN"],
        "FETC:BLER:STATE?": ["NOTRDY", "RDY"],
        "FETC:BLER?": ["7.25"],
    }
    controller, transport = _controller(tmp_path, responses)
    controller.lte_prepare_cell("B3", 1300, bw=20, packet_count=1000)

    assert controller.wait_for_attach()
    assert controller.measure_bler(1000) == pytest.approx(7.25)
    assert transport.queries.count("RRC?") == 2
    assert transport.queries.count("FETC:BLER:STATE?") == 2


@pytest.mark.parametrize("response", ["-0.01", "100.01", "nan"])
def test_real_measurement_never_falls_back_and_validates_bler(tmp_path, response) -> None:
    responses = {
        "FETC:BLER:STATE?": ["RDY"],
        "FETC:BLER?": [response],
    }
    controller, transport = _controller(tmp_path, responses)

    with pytest.raises((RuntimeError, ValueError)):
        controller.measure_bler(1000)
    assert controller.fallback_simulation is False
    assert transport.writes[-1] == "STOP:BLER"


def test_real_measurement_transport_error_is_propagated(tmp_path) -> None:
    controller, _ = _controller(
        tmp_path,
        {"FETC:BLER:STATE?": ["RDY"]},
    )

    with pytest.raises(RuntimeError, match="no response"):
        controller.measure_bler(1000)


def test_cleanup_query_is_consumed_and_asserted(tmp_path) -> None:
    controller, transport = _controller(tmp_path, {"SYST:ERR?": ['0,"No error"']})

    controller.lte_cleanup()

    assert transport.queries == ["SYST:ERR?"]
    assert controller.command_trace[-1]["operation"] == "query_and_assert"
    assert controller.command_trace[-1]["response"] == '0,"No error"'


def test_failed_query_assert_is_traced_and_raised(tmp_path) -> None:
    controller, _ = _controller(tmp_path, {"SYST:ERR?": ['-100,"Command error"']})

    with pytest.raises(RuntimeError, match="响应断言失败"):
        controller.lte_cleanup()
    assert controller.command_trace[-1]["success"] is False
    assert controller.command_trace[-1]["response"].startswith("-100")


def test_cancel_checker_prevents_new_instrument_command(tmp_path) -> None:
    controller, transport = _controller(tmp_path, {"CONF:FREQ?": ["1805E6"]})
    controller.set_cancel_checker(lambda: True)

    with pytest.raises(RuntimeError, match="取消"):
        controller.lte_prepare_cell("B1", 100, bw=20, packet_count=1000)
    assert transport.writes == []


def test_cmw500_idn_validation() -> None:
    idn = "Rohde&Schwarz,CMW500,123456,3.8.10"
    assert is_cmw500_idn(idn)
    assert validate_cmw500_idn(idn) == idn
    assert not is_cmw500_idn("Fake CMW500 Simulator")
    with pytest.raises(RuntimeError, match="不是受支持"):
        validate_cmw500_idn("ACME,SignalGenerator,1,1.0")
