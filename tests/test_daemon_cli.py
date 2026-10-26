"""The CLI/bar contract is identical with a direct mouse or the daemon socket."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput

from maestro import __main__ as cli
from maestro import hidpp, mouse
from maestro.daemon import ipc
from maestro.daemon.actions import Actions
from maestro.daemon.config import ConfigFile
from maestro.daemon.profiles import resolve
from maestro.daemon.service import Daemon, MouseSession


class CLIRoutingTests(unittest.TestCase):
    def test_cli_against_daemon_handler_with_real_json_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
            daemon.actions = Actions(FakeOutput())
            self.addCleanup(daemon.close)
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))

            def exchange(message):
                return json.loads(json.dumps(daemon.handle(json.loads(json.dumps(message)))))

            with (
                patch.object(ipc, "request_if_running", side_effect=exchange),
                patch.object(ipc, "request", side_effect=exchange),
                patch.object(mouse, "find_mice") as direct,
            ):
                for argv in (
                    ["status", "--json"],
                    ["dpi", "1200", "--json"],
                    ["smartshift", "--threshold", "20", "--json"],
                    ["scroll", "--invert", "on", "--json"],
                ):
                    code, output, error = self.invoke(argv)
                    self.assertEqual(code, 0, error)
                    expected = mouse.status(device)
                    self.assertEqual(
                        json.loads(output), [expected] if argv[0] == "status" else expected
                    )
                direct.assert_not_called()
            self.assertEqual(device.dpi, 1200)
            self.assertEqual(device.smartshift[1], 20)
            self.assertEqual(device.wheel_flags & 4, 4)

    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def remote_status(self, devices):
        return {
            "ok": True,
            "devices": [
                dict(
                    mouse.status(d),
                    writable=d.writable,
                    online=True,
                    profile=None,
                    errors=[],
                    diverted_controls=[0xC3],
                    thumb_diverted=False,
                )
                for d in devices
            ],
        }

    def test_status_json_and_plain_text_match_direct_including_selectors(self):
        known, unknown = FakeDevice(), FakeDevice("M720 Triathlon")
        unknown.index = 2
        devices = [unknown, known]
        response = self.remote_status(devices)
        for argv in (
            ["status", "--json"],
            ["status"],
            ["status", "--all", "--json"],
            ["status", "--mouse", "0", "--json"],
            ["--device", "/dev/fake:1", "status", "--json"],
            ["status", "--device", "/dev/fake"],
            ["status", "--mouse", "9"],
        ):
            with self.subTest(argv=argv):
                with (
                    patch.object(ipc, "request_if_running", return_value=None),
                    patch.object(mouse, "find_mice", return_value=devices) as direct,
                    patch.object(hidpp, "close_devices"),
                ):
                    expected = self.invoke(argv)
                    direct.assert_called_once_with(include_unsupported=True)
                with (
                    patch.object(ipc, "request_if_running", return_value=response),
                    patch.object(mouse, "find_mice") as direct,
                    patch.object(hidpp, "Channel") as channel,
                ):
                    self.assertEqual(self.invoke(argv), expected)
                    direct.assert_not_called()
                    channel.assert_not_called()

    def test_every_write_command_uses_ipc_and_preserves_json_and_plain_output(self):
        cases = [
            (["dpi", "1200"], {"dpi": 1200}),
            (["smartshift", "--threshold", "20"], {"smartshift": {"threshold": 20}}),
            (["smartshift", "--mode", "freespin"], {"smartshift": {"mode": "freespin"}}),
            (["scroll", "--invert", "on"], {"invert": True}),
            (["scroll", "--invert", "off"], {"invert": False}),
        ]
        for command, settings in cases:
            for json_output in (False, True):
                with self.subTest(command=command, json=json_output):
                    device = FakeDevice()
                    argv = command + (["--json"] if json_output else [])
                    with (
                        patch.object(ipc, "request_if_running", return_value=None),
                        patch.object(mouse, "find_mice", return_value=[device]),
                        patch.object(hidpp, "close_devices"),
                    ):
                        expected = self.invoke(argv)
                    snapshot = mouse.status(device)
                    with (
                        patch.object(
                            ipc, "request_if_running", return_value=self.remote_status([device])
                        ),
                        patch.object(
                            ipc, "request", return_value={"ok": True, "status": snapshot}
                        ) as request,
                        patch.object(mouse, "find_mice") as direct,
                        patch.object(hidpp, "Channel") as channel,
                    ):
                        self.assertEqual(self.invoke(argv), expected)
                        request.assert_called_once_with(
                            {
                                "op": "set",
                                "device": 0,
                                "settings": settings,
                                "selector": {
                                    "path": "/dev/fake",
                                    "index": 1,
                                    "model": "MX Master 2S",
                                },
                            }
                        )
                        direct.assert_not_called()
                        channel.assert_not_called()
                    if json_output:
                        self.assertEqual(json.loads(expected[1]), snapshot)

    def test_running_daemon_errors_never_fall_back_to_hidraw(self):
        for error in (
            TimeoutError("daemon timed out"),
            PermissionError("denied"),
            ConnectionError("socket closed"),
        ):
            for argv in (
                ["status", "--json"],
                ["dpi", "1200"],
                ["smartshift", "--threshold", "20"],
                ["scroll", "--invert", "on"],
            ):
                with (
                    self.subTest(error=error, argv=argv),
                    patch.object(ipc, "request_if_running", side_effect=error),
                    patch.object(mouse, "find_mice") as direct,
                ):
                    self.assertEqual(self.invoke(argv)[0], 1)
                    direct.assert_not_called()

    def test_socket_write_failures_and_read_only_identity_do_not_open_hidraw(self):
        device = FakeDevice(writable=False)
        with (
            patch.object(ipc, "request_if_running", return_value=self.remote_status([device])),
            patch.object(ipc, "request") as request,
            patch.object(mouse, "find_mice") as direct,
        ):
            self.assertEqual(self.invoke(["dpi", "1200"])[0], 2)
            request.assert_not_called()
            direct.assert_not_called()
        device.writable = True
        with (
            patch.object(ipc, "request_if_running", return_value=self.remote_status([device])),
            patch.object(ipc, "request", return_value={"ok": False, "error": "mouse asleep"}),
            patch.object(mouse, "find_mice") as direct,
        ):
            result = self.invoke(["dpi", "1200"])
            self.assertEqual(result[0], 1)
            self.assertIn("mouse asleep", result[2])
            direct.assert_not_called()

    def test_diagnose_uses_owner_socket_too(self):
        device = FakeDevice()
        report = {"schema": 1, "devices": [{"model": device.model}], "sleeping": []}
        with (
            patch.object(ipc, "request_if_running", return_value=self.remote_status([device])),
            patch.object(ipc, "request", return_value={"ok": True, "report": report}) as request,
            patch.object(mouse, "find_mice") as direct,
        ):
            code, stdout, _ = self.invoke(["diagnose", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout), report)
            request.assert_called_once_with({"op": "diagnose", "devices": [0]})
            direct.assert_not_called()

    def test_rejected_arguments_keep_cli_exit_code_two(self):
        device = FakeDevice()
        for argv in (["dpi", "1234"], ["smartshift", "--threshold", "0"]):
            with (
                self.subTest(argv=argv),
                patch.object(ipc, "request_if_running", return_value=self.remote_status([device])),
                patch.object(
                    ipc,
                    "request",
                    return_value={"ok": False, "error": "invalid setting", "exit_code": 2},
                ),
                patch.object(mouse, "find_mice") as direct,
            ):
                self.assertEqual(self.invoke(argv)[0], 2)
                direct.assert_not_called()
