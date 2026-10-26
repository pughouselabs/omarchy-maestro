import fcntl
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro.daemon.ipc import Server, request_if_running


class IPCTests(unittest.TestCase):
    def test_direct_fallback_only_when_socket_and_daemon_owner_are_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maestro.sock"
            self.assertIsNone(request_if_running({"op": "status"}, path))
            stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            stale.bind(str(path))
            stale.close()
            self.assertIsNone(request_if_running({"op": "status"}, path))
            lock = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ConnectionError, "maestrod owns HID"):
                    request_if_running({"op": "status"}, path)
                path.unlink()
                with self.assertRaises(ConnectionError):
                    request_if_running({"op": "status"}, path)
            finally:
                os.close(lock)
            self.assertIsNone(request_if_running({"op": "status"}, path))

    def test_running_owner_timeouts_and_permission_errors_never_allow_fallback(self):
        for error in (TimeoutError("slow"), PermissionError("private socket")):
            with self.subTest(error=error), patch("maestro.daemon.ipc.request", side_effect=error):
                with self.assertRaises(type(error)):
                    request_if_running({"op": "status"}, "/unused/maestro.sock")

    def test_partial_frame_error_and_one_response_per_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maestro.sock"
            server = Server(lambda request: {"ok": True, "op": request["op"]}, path)
            self.addCleanup(server.close)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(path))
                client.sendall(b'{"op":')
                server.poll()
                self.assertEqual(len(server.clients), 1)
                client.sendall(b'"status"}\n')
                server.poll()
                self.assertEqual(json.loads(client.recv(4096)), {"ok": True, "op": "status"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect(str(path))
                client.sendall(b"[]\n")
                server.poll()
                self.assertIn("JSON object", json.loads(client.recv(4096))["error"])
            server.close()
            self.assertFalse(path.exists())

    def test_handler_type_error_returns_json_and_next_request_still_works(self):
        def handler(message):
            if message["op"] == "bad":
                raise TypeError("wrong field type")
            return {"ok": True}

        with tempfile.TemporaryDirectory() as directory:
            server = Server(handler, Path(directory) / "maestro.sock")
            try:
                for op, expected in (("bad", False), ("good", True)):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.settimeout(1)
                        client.connect(str(server.path))
                        client.sendall(json.dumps({"op": op}).encode() + b"\n")
                        server.poll()
                        result = json.loads(client.recv(4096))
                    self.assertEqual(result["ok"], expected)
                    if not expected:
                        self.assertIn("wrong field type", result["error"])
            finally:
                server.close()

    def test_duplicate_daemon_cannot_unlink_owner_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maestro.sock"
            server = Server(lambda request: {}, path)
            self.addCleanup(server.close)
            inode = path.stat().st_ino
            with self.assertRaises(BlockingIOError):
                Server(lambda request: {}, path)
            self.assertEqual(path.stat().st_ino, inode)

    def test_stale_socket_replaced_but_regular_file_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maestro.sock"
            stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            stale.bind(str(path))
            stale.close()
            server = Server(lambda request: {}, path)
            server.close()
            path.write_text("do not replace")
            with self.assertRaisesRegex(RuntimeError, "non-socket"):
                Server(lambda request: {}, path)
            self.assertEqual(path.read_text(), "do not replace")

    def test_idle_clients_expire_without_blocking_event_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server(lambda request: {}, Path(directory) / "maestro.sock")
            self.addCleanup(server.close)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(server.path))
                server.poll(now=10)
                server.poll(now=16)
                self.assertFalse(server.clients)
