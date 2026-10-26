"""Bounded newline-delimited JSON over a private Unix socket."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import socket
import stat
import struct
import time
from pathlib import Path

from maestro.hidpp import HidppError, NoResponse

MAX_MESSAGE = 65536
LOG = logging.getLogger("maestrod")


def socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise RuntimeError("XDG_RUNTIME_DIR is unset; start maestrod in your desktop session")
    return Path(runtime) / "maestro.sock"


def request(message, path=None, timeout=5.0):
    """Client entry point for CLI/widget integrations. Does not open hidraw."""
    payload = json.dumps(message, allow_nan=False).encode() + b"\n"
    if len(payload) > MAX_MESSAGE:
        raise ValueError("IPC request is too large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path or socket_path()))
        connection.sendall(payload)
        data = bytearray()
        while b"\n" not in data:
            chunk = connection.recv(4096)
            if not chunk:
                raise ConnectionError("daemon closed the socket without a response")
            data.extend(chunk)
            if len(data) > MAX_MESSAGE:
                raise ValueError("IPC response is too large")
        return json.loads(data.split(b"\n", 1)[0])


def request_if_running(message, path=None, timeout=5.0):
    """Return None only when neither a listener nor a daemon lock is active."""
    if path is None and not os.environ.get("XDG_RUNTIME_DIR"):
        return None
    endpoint = Path(path) if path is not None else socket_path()
    try:
        return request(message, path=endpoint, timeout=timeout)
    except (FileNotFoundError, ConnectionRefusedError) as exc:
        try:
            fd = os.open(str(endpoint) + ".lock", os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ConnectionError(
                    "maestrod owns HID++; its socket is not ready, retry shortly"
                ) from exc
        finally:
            os.close(fd)
        return None


class Server:
    def __init__(self, handler, path=None):
        self.handler = handler
        self.path = Path(path) if path else socket_path()
        self.clients = {}
        self.listener = None
        self.lock_fd = -1
        self.inode = None
        parent = self.path.parent.stat()
        if parent.st_uid != os.getuid() or parent.st_mode & 0o022:
            raise RuntimeError(
                "IPC directory must be owned by this user and not writable by others"
            )
        try:
            self.lock_fd = os.open(
                str(self.path) + ".lock",
                os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.path.exists() or self.path.is_symlink():
                previous = self.path.lstat()
                if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.getuid():
                    raise RuntimeError(
                        f"refusing to replace non-socket or foreign socket {self.path}"
                    )
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.1)
                    try:
                        probe.connect(str(self.path))
                    except (ConnectionRefusedError, FileNotFoundError):
                        pass
                    else:
                        raise RuntimeError(f"a daemon is already listening at {self.path}")
                # The lock owns this endpoint. A socket left after a crash is stale.
                self.path.unlink()
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(str(self.path))
            self.inode = self.path.stat().st_ino
            self.path.chmod(0o600)
            self.listener.listen(8)
            self.listener.setblocking(False)
        except BaseException:
            self.close()
            raise

    def poll(self, now=None):
        now = time.monotonic() if now is None else now
        for _ in range(8):
            try:
                connection, _ = self.listener.accept()
            except BlockingIOError:
                break
            uid = struct.unpack(
                "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )[1]
            if uid != os.getuid() or len(self.clients) >= 16:
                connection.close()
                continue
            connection.setblocking(False)
            self.clients[connection] = {"in": bytearray(), "out": None, "deadline": now + 5}
        for connection, state in list(self.clients.items()):
            try:
                if now >= state["deadline"]:
                    self._drop(connection)
                    continue
                if state["out"] is None:
                    try:
                        chunk = connection.recv(4096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        self._drop(connection)
                        continue
                    state["in"].extend(chunk)
                    if len(state["in"]) > MAX_MESSAGE:
                        result = {"ok": False, "error": "request exceeds 65536 bytes"}
                    elif b"\n" not in state["in"]:
                        continue
                    else:
                        try:
                            message = json.loads(state["in"].split(b"\n", 1)[0])
                            if not isinstance(message, dict):
                                raise ValueError("request must be a JSON object")
                            result = self.handler(message)
                        except Exception as exc:
                            if not isinstance(
                                exc,
                                (
                                    ValueError,
                                    TypeError,
                                    KeyError,
                                    OSError,
                                    RuntimeError,
                                    HidppError,
                                    NoResponse,
                                ),
                            ):
                                LOG.exception("IPC request failed")
                            result = {
                                "ok": False,
                                "error": str(exc),
                                "exit_code": 2
                                if isinstance(exc, (ValueError, TypeError, KeyError))
                                else 1,
                            }
                    try:
                        state["out"] = json.dumps(result, allow_nan=False).encode() + b"\n"
                    except (TypeError, ValueError, OverflowError) as exc:
                        LOG.exception("IPC response could not be encoded")
                        state["out"] = (
                            json.dumps({"ok": False, "error": str(exc), "exit_code": 1}).encode()
                            + b"\n"
                        )
                    if len(state["out"]) > MAX_MESSAGE:
                        state["out"] = b'{"ok":false,"error":"response too large"}\n'
                try:
                    sent = connection.send(state["out"])
                    state["out"] = state["out"][sent:]
                except BlockingIOError:
                    continue
                if not state["out"]:
                    self._drop(connection)
            except (OSError, UnicodeError):
                self._drop(connection)

    def _drop(self, connection):
        connection.close()
        self.clients.pop(connection, None)

    def close(self):
        for connection in list(self.clients):
            self._drop(connection)
        if self.listener is not None:
            self.listener.close()
            self.listener = None
        if self.inode is not None:
            try:
                if self.path.lstat().st_ino == self.inode:
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self.inode = None
        if self.lock_fd >= 0:
            os.close(self.lock_fd)
            self.lock_fd = -1
