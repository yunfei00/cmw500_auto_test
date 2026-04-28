from __future__ import annotations

import socket


class ScpiSocketClient:
    def __init__(self, host: str, port: int = 5025, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: socket.socket | None = None

    def connect(self) -> None:
        try:
            self.disconnect()
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._socket.settimeout(self.timeout)
        except OSError as exc:
            self._socket = None
            raise RuntimeError(f"SCPI Socket 连接失败：{self.host}:{self.port}，{exc}") from exc

    def disconnect(self) -> None:
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
        finally:
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
        try:
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
        except socket.timeout as exc:
            if not chunks:
                raise RuntimeError(f"SCPI 查询超时：{command}") from exc
        except OSError as exc:
            raise RuntimeError(f"SCPI 查询失败：{command}，{exc}") from exc

        if not chunks:
            raise RuntimeError(f"SCPI 查询无返回：{command}")
        return b"".join(chunks).decode("utf-8", errors="replace").strip()
