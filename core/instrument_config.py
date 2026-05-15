from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisaConfig:
    resource: str = "TCPIP0::169.254.65.34::inst0::INSTR"
    timeout_ms: int = 10000


@dataclass
class SocketConfig:
    host: str = "169.254.65.34"
    port: int = 5025
    timeout_ms: int = 10000


@dataclass
class InstrumentConfig:
    type: str = "visa"
    visa: VisaConfig = field(default_factory=VisaConfig)
    socket: SocketConfig = field(default_factory=SocketConfig)


def load_instrument_config(raw: dict[str, Any] | None) -> InstrumentConfig:
    raw = raw or {}
    inst_raw = raw.get("instrument") if "instrument" in raw else raw
    if not isinstance(inst_raw, dict):
        inst_raw = {}

    if "type" not in inst_raw and ("ip" in inst_raw or "port" in inst_raw):
        inst_raw = {
            "type": "socket",
            "socket": {
                "host": str(inst_raw.get("ip", SocketConfig.host)),
                "port": int(inst_raw.get("port", SocketConfig.port)),
                "timeout_ms": int(inst_raw.get("timeout_ms", SocketConfig.timeout_ms)),
            },
            "visa": {"resource": VisaConfig.resource, "timeout_ms": VisaConfig.timeout_ms},
        }

    visa_raw = inst_raw.get("visa") if isinstance(inst_raw.get("visa"), dict) else {}
    socket_raw = inst_raw.get("socket") if isinstance(inst_raw.get("socket"), dict) else {}

    return InstrumentConfig(
        type=str(inst_raw.get("type", "visa")).lower(),
        visa=VisaConfig(
            resource=str(visa_raw.get("resource", VisaConfig.resource)),
            timeout_ms=int(visa_raw.get("timeout_ms", VisaConfig.timeout_ms)),
        ),
        socket=SocketConfig(
            host=str(socket_raw.get("host", SocketConfig.host)),
            port=int(socket_raw.get("port", SocketConfig.port)),
            timeout_ms=int(socket_raw.get("timeout_ms", SocketConfig.timeout_ms)),
        ),
    )
