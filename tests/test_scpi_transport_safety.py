from __future__ import annotations

import socket
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from devices.instrument_transport import (
    InstrumentCancelledError,
    SocketTransport,
    VisaTransport,
    create_visa_resource_manager,
)


def test_socket_query_can_be_cancelled_and_invalidates_stream() -> None:
    fake_socket = MagicMock()
    fake_socket.recv.side_effect = socket.timeout()
    checks = 0

    def cancel_checker() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with patch("socket.create_connection", return_value=fake_socket):
        transport = SocketTransport("169.254.65.34", timeout_ms=5000)
        transport.set_cancel_checker(cancel_checker)
        transport.connect()
        with pytest.raises(InstrumentCancelledError):
            transport.query("*IDN?")

    assert not transport.is_connected()
    fake_socket.close.assert_called()


def test_socket_send_error_marks_transport_disconnected() -> None:
    fake_socket = MagicMock()
    fake_socket.sendall.side_effect = OSError("connection reset")
    with patch("socket.create_connection", return_value=fake_socket):
        transport = SocketTransport("169.254.65.34")
        transport.connect()
        with pytest.raises(RuntimeError, match="发送失败"):
            transport.write("*RST")

    assert not transport.is_connected()


def test_visa_query_error_marks_transport_disconnected() -> None:
    fake_inst = MagicMock()
    fake_inst.query.side_effect = OSError("device lost")
    fake_rm = MagicMock()
    fake_rm.open_resource.return_value = fake_inst
    fake_pyvisa = types.SimpleNamespace(ResourceManager=MagicMock(return_value=fake_rm))

    with patch.dict(sys.modules, {"pyvisa": fake_pyvisa}):
        transport = VisaTransport("TCPIP0::169.254.65.34::inst0::INSTR")
        transport.connect()
        with pytest.raises(RuntimeError, match="VISA 查询失败"):
            transport.query("*IDN?")

    assert not transport.is_connected()
    fake_inst.close.assert_called()


def test_visa_manager_falls_back_to_bundled_python_backend() -> None:
    fallback_manager = object()
    fake_pyvisa = types.SimpleNamespace(
        ResourceManager=MagicMock(
            side_effect=[RuntimeError("system VISA unavailable"), fallback_manager]
        )
    )

    assert create_visa_resource_manager(fake_pyvisa) is fallback_manager
    assert fake_pyvisa.ResourceManager.call_args_list[1].args == ("@py",)
