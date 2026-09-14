from __future__ import annotations

from collections import defaultdict

import pytest

from devices.cmw500_controller import RealCMW500
from devices.instrument_transport import InstrumentTransport


class ScriptedTransport(InstrumentTransport):
    def __init__(self, responses: dict[str, list[str]]) -> None:
        self.connected = False
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.responses: defaultdict[str, list[str]] = defaultdict(list)
        for command, values in responses.items():
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
        if not self.responses[command]:
            raise RuntimeError(f"no response for {command}")
        return self.responses[command].pop(0)

    def is_connected(self) -> bool:
        return self.connected


def _controller(responses: dict[str, list[str]]) -> tuple[RealCMW500, ScriptedTransport]:
    transport = ScriptedTransport(responses)
    controller = RealCMW500(transport)
    controller.connect()
    return controller, transport


def test_lte_prepare_run_skips_matching_com_and_uses_fixed_order() -> None:
    route = "RF1C,RX1,RF1C,TX1"
    controller, transport = _controller(
        {
            "ROUTe:LTE:SIGN:SCENario:SCELl?": [route],
            "CONFigure:LTE:SIGN:RFSettings:EATTenuation:INPut?": ["35"],
            "CONFigure:LTE:SIGN:RFSettings:EATTenuation:OUTPut?": ["35"],
        }
    )

    controller.lte_prepare_run(com_port=1, cable_loss=35)

    assert transport.writes == [
        "INST LTE",
        "CONFigure:LTE:SIGN:RFSettings:EATTenuation:INPut 35",
        "CONFigure:LTE:SIGN:RFSettings:EATTenuation:OUTPut 35",
        "CONFigure:LTE:SIGN:UEReport:ENABle ON",
        "CONFigure:LTE:SIGN:UL:PUSCh:TPC:SET MAXP",
        "CONFigure:LTE:SIGN:UL:PMAX 23",
        "CONFigure:LTE:SIGN:CONNection:PCC:STYPe RMC",
        "CONFigure:LTE:SIGN:CELL:SECurity:AUTHenticat ON",
        "CONFigure:LTE:SIGN:CELL:SECurity:NAS ON",
        "CONFigure:LTE:SIGN:CELL:SECurity:AS ON",
        "CONFigure:LTE:SIGN:CELL:SECurity:IALGorithm S3G",
    ]
    assert controller.current_com_port == 1
    assert controller.current_cable_loss == pytest.approx(35.0)
    assert controller.uses_external_cable_loss_compensation is True


def test_lte_prepare_run_changes_com_and_verifies_route() -> None:
    query = "ROUTe:LTE:SIGN:SCENario:SCELl?"
    controller, transport = _controller(
        {
            query: ["RF1C,RX1,RF1C,TX1", "RF3C,RX2,RF3C,TX2"],
            "CONFigure:LTE:SIGN:RFSettings:EATTenuation:INPut?": ["12.5"],
            "CONFigure:LTE:SIGN:RFSettings:EATTenuation:OUTPut?": ["12.5"],
        }
    )

    controller.lte_prepare_run(com_port=3, cable_loss=12.5)

    assert transport.queries[:2] == [query, query]
    assert "ROUTe:LTE:SIGN:SCENario:SCELl RF3C,RX2,RF3C,TX2" in transport.writes
    assert controller.current_com_port == 3


def test_lte_prepare_run_fails_closed_on_line_loss_verify_mismatch() -> None:
    controller, transport = _controller(
        {
            "ROUTe:LTE:SIGN:SCENario:SCELl?": ["RF1C,RX1,RF1C,TX1"],
            "CONFigure:LTE:SIGN:RFSettings:EATTenuation:INPut?": ["34"],
        }
    )

    with pytest.raises(RuntimeError, match="输入线损回读不一致"):
        controller.lte_prepare_run(com_port=1, cable_loss=35)

    assert "CONFigure:LTE:SIGN:RFSettings:EATTenuation:OUTPut 35" not in transport.writes
    assert "SOURce:LTE:SIGN:CELL:STATe ON" not in transport.writes
