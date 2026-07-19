from __future__ import annotations

import socket
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable


class InstrumentCancelledError(RuntimeError):
    """Raised when a blocking instrument operation is cancelled."""


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

    def set_cancel_checker(self, checker: Callable[[], bool] | None) -> None:
        self._external_cancel_checker = checker

    def request_cancel(self) -> None:
        self._cancel_event().set()

    def clear_cancel(self) -> None:
        self._cancel_event().clear()

    def abort_io(self) -> None:
        self.request_cancel()
        self.close()

    def _cancel_event(self) -> threading.Event:
        event = getattr(self, "_transport_cancel_event", None)
        if event is None:
            event = threading.Event()
            self._transport_cancel_event = event
        return event

    def _check_cancelled(self) -> None:
        checker = getattr(self, "_external_cancel_checker", None)
        external_cancelled = bool(checker()) if checker is not None else False
        if self._cancel_event().is_set() or external_cancelled:
            raise InstrumentCancelledError("仪表操作已取消")


def create_visa_resource_manager(pyvisa_module=None):
    """Open the system VISA backend, falling back to bundled pyvisa-py."""

    if pyvisa_module is None:
        try:
            import pyvisa as pyvisa_module
        except ImportError as exc:
            raise RuntimeError("缺少 pyvisa，请重新安装应用") from exc
    try:
        return pyvisa_module.ResourceManager()
    except Exception as system_error:
        try:
            return pyvisa_module.ResourceManager("@py")
        except Exception as python_error:
            raise RuntimeError(
                "无法加载系统 VISA 或内置 pyvisa-py 后端："
                f"system={system_error}; pyvisa-py={python_error}"
            ) from python_error


class VisaTransport(InstrumentTransport):
    def __init__(self, resource: str, timeout_ms: int = 10000) -> None:
        self.resource = resource
        self.timeout_ms = timeout_ms
        self._rm = None
        self._inst = None
        self.backend = ""
        self._io_lock = threading.RLock()

    def connect(self) -> None:
        try:
            import pyvisa
        except ImportError as exc:
            raise RuntimeError("缺少 pyvisa，请先安装 pyvisa") from exc

        with self._io_lock:
            self.clear_cancel()
            self.close()
            try:
                self._rm = create_visa_resource_manager(pyvisa)
                self.backend = str(getattr(self._rm, "visalib", "unknown"))
                self._inst = self._rm.open_resource(self.resource)
                self._inst.timeout = self.timeout_ms
                self._inst.write_termination = "\n"
                self._inst.read_termination = "\n"
            except Exception as exc:
                self.close()
                raise RuntimeError(f"VISA 连接失败：{self.resource}，{exc}") from exc

    def close(self) -> None:
        # Do not take _io_lock here: abort_io may need to close a resource while
        # another thread is blocked inside a VISA call.
        inst, rm = self._inst, self._rm
        self._inst = None
        self._rm = None
        if inst is not None:
            try:
                inst.close()
            except Exception:
                pass
        if rm is not None:
            try:
                rm.close()
            except Exception:
                pass

    def write(self, command: str) -> None:
        with self._io_lock:
            self._check_cancelled()
            inst = self._inst
            if inst is None:
                raise RuntimeError("VISA 未连接")
            try:
                inst.write(command)
                self._check_cancelled()
            except InstrumentCancelledError:
                self.close()
                raise
            except Exception as exc:
                self.close()
                raise RuntimeError(f"VISA 命令发送失败：{command}，{exc}") from exc

    def query(self, command: str) -> str:
        with self._io_lock:
            self._check_cancelled()
            inst = self._inst
            if inst is None:
                raise RuntimeError("VISA 未连接")
            try:
                response = str(inst.query(command)).strip()
                self._check_cancelled()
                return response
            except InstrumentCancelledError:
                self.close()
                raise
            except Exception as exc:
                self.close()
                raise RuntimeError(f"VISA 查询失败：{command}，{exc}") from exc

    def is_connected(self) -> bool:
        return self._inst is not None


class SocketTransport(InstrumentTransport):
    def __init__(self, host: str, port: int = 5025, timeout_ms: int = 10000) -> None:
        self.host = host
        self.port = port
        self.timeout_ms = timeout_ms
        self._socket: socket.socket | None = None
        self._io_lock = threading.RLock()

    @property
    def _timeout_sec(self) -> float:
        return max(self.timeout_ms / 1000.0, 0.001)

    @property
    def _poll_timeout_sec(self) -> float:
        return min(self._timeout_sec, 0.1)

    def connect(self) -> None:
        with self._io_lock:
            self.clear_cancel()
            self.close()
            try:
                connected = socket.create_connection(
                    (self.host, self.port), timeout=self._timeout_sec
                )
                connected.settimeout(self._poll_timeout_sec)
                self._socket = connected
            except OSError as exc:
                self._socket = None
                raise RuntimeError(
                    f"SCPI Socket 连接失败：{self.host}:{self.port}，{exc}"
                ) from exc

    def close(self) -> None:
        # Intentionally lock-free so abort_io can interrupt a blocking recv.
        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def is_connected(self) -> bool:
        return self._socket is not None

    def write(self, command: str) -> None:
        with self._io_lock:
            self._check_cancelled()
            sock = self._socket
            if sock is None:
                raise RuntimeError("SCPI Socket 未连接")
            try:
                self._send(sock, command)
                self._check_cancelled()
            except InstrumentCancelledError:
                self._drop_socket(sock)
                raise
            except OSError as exc:
                self._drop_socket(sock)
                raise RuntimeError(f"SCPI 命令发送失败：{command}，{exc}") from exc

    def query(self, command: str) -> str:
        with self._io_lock:
            self._check_cancelled()
            sock = self._socket
            if sock is None:
                raise RuntimeError("SCPI Socket 未连接")
            try:
                self._send(sock, command)
                chunks: list[bytes] = []
                deadline = time.monotonic() + self._timeout_sec
                while time.monotonic() < deadline:
                    self._check_cancelled()
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        self._drop_socket(sock)
                        if chunks:
                            break
                        raise RuntimeError(
                            f"SCPI 连接已由仪表关闭，查询无返回：{command}"
                        )
                    chunks.append(chunk)
                    if b"\n" in chunk:
                        break

                self._check_cancelled()
                if not chunks:
                    raise RuntimeError(f"SCPI 查询超时或无返回：{command}")
                return b"".join(chunks).decode("utf-8", errors="replace").strip()
            except InstrumentCancelledError:
                # A cancelled query may still have a late response. Closing the
                # socket prevents that response from corrupting the next query.
                self._drop_socket(sock)
                raise
            except RuntimeError:
                # Query timeouts and peer-close errors invalidate the stream.
                self._drop_socket(sock)
                raise
            except OSError as exc:
                self._drop_socket(sock)
                raise RuntimeError(f"SCPI 查询失败：{command}，{exc}") from exc

    def abort_io(self) -> None:
        self.request_cancel()
        self.close()

    @staticmethod
    def _send(sock: socket.socket, command: str) -> None:
        data = command if command.endswith("\n") else f"{command}\n"
        sock.sendall(data.encode("utf-8"))

    def _drop_socket(self, sock: socket.socket) -> None:
        if self._socket is sock:
            self._socket = None
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
