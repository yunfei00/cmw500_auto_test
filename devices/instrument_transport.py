from __future__ import annotations

import socket
import time
from abc import ABC, abstractmethod


class InstrumentTransport(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def write(self, command: str) -> None: ...

    @abstractmethod
    def query(self, command: str) -> str: ...

    @abstractmethod
    def is_connected(self) -> bool: ...


class VisaTransport(InstrumentTransport):
    def __init__(self, resource: str, timeout_ms: int = 10000) -> None:
        self.resource = resource
        self.timeout_ms = timeout_ms
        self._rm = None
        self._inst = None

    def connect(self) -> None:
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("缺少 pyvisa，请先安装 pyvisa") from exc

        try:
            self.close()
            self._rm = pyvisa.ResourceManager()
            self._inst = self._rm.open_resource(self.resource)
            self._inst.timeout = self.timeout_ms
            self._inst.write_termination = "\n"
            self._inst.read_termination = "\n"
        except Exception as exc:
            self.close()
            raise RuntimeError(f"VISA 连接失败：{self.resource}，{exc}") from exc

    def close(self) -> None:
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:
                pass
            self._inst = None
        if self._rm is not None:
            try:
                self._rm.close()
            except Exception:
                pass
            self._rm = None

    def write(self, command: str) -> None:
        if self._inst is None:
            raise RuntimeError("VISA 未连接")
        self._inst.write(command)

    def query(self, command: str) -> str:
        if self._inst is None:
            raise RuntimeError("VISA 未连接")
        return str(self._inst.query(command)).strip()

    def is_connected(self) -> bool:
        return self._inst is not None


class SocketTransport(InstrumentTransport):
    def __init__(self, host: str, port: int = 5025, timeout_ms: int = 10000) -> None:
        self.host = host
        self.port = port
        self.timeout_ms = timeout_ms
        self._socket: socket.socket | None = None

    @property
    def _timeout_sec(self) -> float:
        return max(self.timeout_ms / 1000.0, 0.001)

    def connect(self) -> None:
        try:
            self.close()
            self._socket = socket.create_connection((self.host, self.port), timeout=self._timeout_sec)
            self._socket.settimeout(self._timeout_sec)
        except OSError as exc:
            self._socket = None
            raise RuntimeError(f"SCPI Socket 连接失败：{self.host}:{self.port}，{exc}") from exc

    def close(self) -> None:
        if not self._socket:
            return
        try:
            self._socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._socket.close()
        except OSError:
            pass
        self._socket = None

    def is_connected(self) -> bool:
        return self._socket is not None

    def write(self, command: str) -> None:
        if not self._socket:
            raise RuntimeError("SCPI Socket 未连接")
        data = command if command.endswith("\n") else f"{command}\n"
        try:
            self._socket.sendall(data.encode("utf-8"))
        except OSError as exc:
            raise RuntimeError(f"SCPI 命令发送失败：{command}，{exc}") from exc

    def query(self, command: str) -> str:
        if not self._socket:
            raise RuntimeError("SCPI Socket 未连接")
        self.write(command)
        chunks: list[bytes] = []
        deadline = time.monotonic() + self._timeout_sec
        while time.monotonic() < deadline:
            try:
                chunk = self._socket.recv(4096)
            except socket.timeout:
                if chunks:
                    break
                continue
            except OSError as exc:
                raise RuntimeError(f"SCPI 查询失败：{command}，{exc}") from exc

            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break

        if not chunks:
            raise RuntimeError(f"SCPI 查询超时或无返回：{command}")
        return b"".join(chunks).decode("utf-8", errors="replace").strip()
