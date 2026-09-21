from devices.cmw500_controller import RealCMW500


class ScriptedTransport:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.commands = []
        self.connected = True
    def set_cancel_checker(self, _checker): pass
    def connect(self): self.connected = True
    def close(self): self.connected = False
    def is_connected(self): return self.connected
    def request_cancel(self): pass
    def clear_cancel(self): pass
    def abort_io(self): pass
    def write(self, command): self.commands.append(command)
    def query(self, command):
        self.commands.append(command)
        values = self.responses.get(command, [])
        if not values: raise AssertionError(f"unexpected query: {command}")
        return values.pop(0)


def test_wcdma_prepare_run_uses_confirmed_common_commands():
    t = ScriptedTransport({
        "ROUTe:WCDMa:SIGN:SCENario:SCELl?": ["RF1C,RX1,RF1C,TX1"],
        "CONFigure:WCDMa:SIGN:RFSettings:CARRier:EATTenuation:INPut?": ["35"],
        "CONFigure:WCDMa:SIGN:RFSettings:CARRier:EATTenuation:OUTPut?": ["35"],
    })
    cmw = RealCMW500(t)
    cmw.wcdma_prepare_run(1, 35)
    assert "CONFigure:WCDMa:MEAS:MEValuation:REPetition SING" in t.commands
    assert "CONFigure:WCDMa:SIGN:CONNection:UETerminate TEST" in t.commands
    assert "CONFigure:WCDMa:SIGN:CONNection:TMODe:TYPE RMC" in t.commands
    assert "CONFigure:WCDMa:SIGN:CONNection:TMODe:RMC:TMODe MODE1" in t.commands
    assert "CONFigure:WCDMa:SIGN:CONNection:TMODe:RMC:DATA PRBS9" in t.commands
    assert "CONFigure:WCDMa:SIGN:UL:TPC:SET ALL1" in t.commands


def test_wcdma_connection_accepts_cest_att():
    t = ScriptedTransport({
        "FETCh:WCDMa:SIGN:CSWitched:STATe?": ["CEST"],
        "FETCh:WCDMa:SIGN:PSWitched:STATe?": ["ATT"],
    })
    assert RealCMW500(t).wcdma_ensure_connected(timeout=0.1, interval=0.01)


def test_wcdma_reg_triggers_connect_then_accepts_cest_on():
    t = ScriptedTransport({
        "FETCh:WCDMa:SIGN:CSWitched:STATe?": ["REG", "CEST"],
        "FETCh:WCDMa:SIGN:PSWitched:STATe?": ["ATT", "ON"],
    })
    assert RealCMW500(t).wcdma_ensure_connected(timeout=0.2, interval=0.01)
    assert "CALL:WCDMa:SIGN:CSWitched:ACTion CONNect" in t.commands


def test_wcdma_ber_reads_second_field_without_percent_conversion():
    t = ScriptedTransport({
        "FETCh:WCDMa:SIGN:CSWitched:STATe?": ["CEST"],
        "FETCh:WCDMa:SIGN:PSWitched:STATe?": ["ATT"],
        "FETCh:WCDMa:SIGN:BER:STATe?": ["RDY"],
        "FETCh:WCDMa:SIGN:BER?": ["0,0.01,0,0"],
    })
    value = RealCMW500(t).wcdma_measure_ber(50)
    assert value == 0.01
