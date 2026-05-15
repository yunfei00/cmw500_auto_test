import sys
import types
from unittest.mock import MagicMock, patch

from devices.instrument_transport import SocketTransport, VisaTransport


def test_visa_transport_with_mock() -> None:
    fake_inst = MagicMock()
    fake_inst.query.return_value = "Rohde&Schwarz,CMW500,123,1.0\n"
    fake_rm = MagicMock()
    fake_rm.open_resource.return_value = fake_inst

    fake_pyvisa = types.SimpleNamespace(ResourceManager=MagicMock(return_value=fake_rm))
    with patch.dict(sys.modules, {"pyvisa": fake_pyvisa}):
        t = VisaTransport("TCPIP0::169.254.65.34::inst0::INSTR", 10000)
        t.connect()
        assert t.is_connected()
        assert t.query("*IDN?").startswith("Rohde")
        t.close()


def test_socket_transport_with_mock() -> None:
    fake_socket = MagicMock()
    fake_socket.recv.side_effect = [b"Rohde&Schwarz,CMW500\n"]
    with patch("socket.create_connection", return_value=fake_socket):
        t = SocketTransport("169.254.65.34", 5025, 10000)
        t.connect()
        resp = t.query("*IDN?")
        fake_socket.sendall.assert_called()
        assert "CMW500" in resp
        t.close()
