from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SerialPortConfig:
    name: str
    port: str
    baudrate: int = 115200
    bytesize: int = 8
    parity: str = "N"
    stopbits: int = 1
    timeout: float = 1.0
    role: str = ""


class SerialConfigManager:
    def __init__(self) -> None:
        self.ports: list[SerialPortConfig] = []

    def load_file(self, file_path: str) -> None:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
        elif suffix in {".yaml", ".yml"}:
            data = self._load_yaml(path)
        else:
            raise ValueError("串口配置文件仅支持 .yaml、.yml、.json")

        serial_ports = data.get("serial_ports") if isinstance(data, dict) else None
        if not isinstance(serial_ports, list):
            raise ValueError("串口配置文件缺少 serial_ports 列表")

        self.ports = [self._parse_port_config(item) for item in serial_ports]

    def get_ports(self) -> list[SerialPortConfig]:
        return list(self.ports)

    def get_by_role(self, role: str) -> SerialPortConfig | None:
        normalized_role = role.strip().lower()
        for port_config in self.ports:
            if port_config.role.strip().lower() == normalized_role:
                return port_config
        return None

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        try:
            import yaml
        except ImportError:
            return self._load_simple_yaml(path)

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data or {}

    def _load_simple_yaml(self, path: Path) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].rstrip()
            if not line.strip() or line.strip() == "serial_ports:":
                continue
            stripped = line.strip()
            if stripped.startswith("- "):
                if current:
                    items.append(current)
                current = {}
                content = stripped[2:].strip()
                if content:
                    key, value = self._parse_yaml_key_value(content)
                    current[key] = value
            elif current is not None and ":" in stripped:
                key, value = self._parse_yaml_key_value(stripped)
                current[key] = value

        if current:
            items.append(current)
        return {"serial_ports": items}

    def _parse_yaml_key_value(self, content: str) -> tuple[str, Any]:
        key, raw_value = content.split(":", 1)
        return key.strip(), self._coerce_value(raw_value.strip())

    def _coerce_value(self, value: str) -> Any:
        if not value:
            return ""
        value = value.strip().strip('"').strip("'")
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _parse_port_config(self, item: dict[str, Any]) -> SerialPortConfig:
        if not isinstance(item, dict):
            raise ValueError("串口配置项必须是对象")
        if not item.get("name") or not item.get("port"):
            raise ValueError("串口配置项必须包含 name 和 port")

        return SerialPortConfig(
            name=str(item["name"]),
            port=str(item["port"]),
            baudrate=int(item.get("baudrate", 115200)),
            bytesize=int(item.get("bytesize", 8)),
            parity=str(item.get("parity", "N")),
            stopbits=int(item.get("stopbits", 1)),
            timeout=float(item.get("timeout", 1.0)),
            role=str(item.get("role", "")),
        )
