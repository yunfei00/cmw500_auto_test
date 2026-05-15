from core.instrument_config import load_instrument_config


def test_load_visa_config() -> None:
    cfg = load_instrument_config(
        {
            "instrument": {
                "type": "visa",
                "visa": {"resource": "TCPIP0::169.254.65.34::inst0::INSTR", "timeout_ms": 12000},
            }
        }
    )
    assert cfg.type == "visa"
    assert cfg.visa.resource.endswith("::INSTR")
    assert cfg.visa.timeout_ms == 12000


def test_load_socket_config() -> None:
    cfg = load_instrument_config({"instrument": {"type": "socket", "socket": {"host": "169.254.65.34", "port": 5025}}})
    assert cfg.type == "socket"
    assert cfg.socket.host == "169.254.65.34"
    assert cfg.socket.port == 5025


def test_migrate_legacy_ip_port() -> None:
    cfg = load_instrument_config({"ip": "10.0.0.1", "port": 5025})
    assert cfg.type == "socket"
    assert cfg.socket.host == "10.0.0.1"
