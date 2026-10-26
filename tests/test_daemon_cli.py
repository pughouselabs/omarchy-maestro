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
from maestro.daemon.events import IDENTITY_PROBLEM
from maestro.daemon.profiles import resolve
from maestro.daemon.service import Daemon, MouseSession


class OfflineIdentityTests(unittest.TestCase):
    """Without the service, CLI writes pass the same unit ID check before each write."""

    COMMANDS = (
        ["dpi", "1200"],
        ["smartshift", "--threshold", "20"],
        ["smartshift", "--mode", "freespin"],
        ["scroll", "--invert", "on"],
        ["scroll", "--invert", "off"],
    )

    def run_cli(self, device, argv):
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(ipc, "request_if_running", return_value=None),
            patch.object(mouse, "find_mice", return_value=[device]),
            patch.object(hidpp, "close_devices"),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def writes(self, device):
        return [c for c in device.calls if hidpp.is_write(*c[:2])]

    def unit_reads(self, device):
        return [c for c in device.calls if c[0] == hidpp.FW_VERSION]

    def test_unreadable_unit_id_writes_nothing(self):
        for argv in self.COMMANDS:
            with self.subTest(argv=argv):
                device = FakeDevice()
                device.wheel_flags = 6  # so "off" would also be a change
                device.unit = b"\0\0\0\0"
                code, out, err = self.run_cli(device, argv)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn(IDENTITY_PROBLEM, err)
                self.assertEqual(self.writes(device), [])

    def test_readable_unit_id_works_as_before(self):
        expected = ["1200\n", "ratchet 20\n", "freespin 16\n", "inverted\n", "normal\n"]
        for argv, output in zip(self.COMMANDS, expected, strict=True):
            with self.subTest(argv=argv):
                device = FakeDevice()
                device.wheel_flags = 6
                code, out, err = self.run_cli(device, argv)
                self.assertEqual((code, err, out), (0, "", output))
                writes = self.writes(device)
                self.assertTrue(writes)
                # One read at open, then one before each write.
                self.assertEqual(len(self.unit_reads(device)), 1 + len(writes))

    def test_a_mouse_swapped_after_open_gets_no_write(self):
        real = cli.guard_device

        def open_then_swap(device):
            gate = real(device)
            device.unit = b"\x01\x02\x03\x04"
            return gate

        for argv in self.COMMANDS:
            with self.subTest(argv=argv), patch.object(cli, "guard_device", open_then_swap):
                device = FakeDevice()
                device.wheel_flags = 6
                code, out, err = self.run_cli(device, argv)
                self.assertEqual(code, 2)
                self.assertIn("device identity changed", err)
                self.assertEqual(self.writes(device), [])


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

    def test_status_lists_a_disconnected_mouse_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
            daemon.actions = Actions(FakeOutput())
            self.addCleanup(daemon.close)
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            online = daemon.handle({"op": "status"})["devices"][0]

            def gone():
                raise hidpp.NoResponse("device did not answer")

            # The mouse stops answering (turned off, asleep or out of range).
            session.diversion.guard = gone
            offline = daemon.handle({"op": "status"})["devices"][0]
            # Same shape as a connected mouse, marked offline.
            self.assertLessEqual(set(online), set(offline))
            self.assertIs(offline["receiver"], True)
            self.assertIs(offline["online"], False)
            self.assertEqual(offline["error"], "device did not answer")

            def exchange(message):
                return json.loads(json.dumps(daemon.handle(json.loads(json.dumps(message)))))

            with patch.object(ipc, "request_if_running", side_effect=exchange):
                code, output, error = self.invoke(["status"])
            self.assertEqual(code, 0, error)
            self.assertIn("receiver slot 1", output)
            self.assertIn("disconnected", output)

    def test_status_printing_tolerates_missing_keys(self):
        # An older service may send a disconnected mouse with only a few keys.
        sparse = {"name": "MX Master 2S", "path": "/dev/hidraw4", "index": 1, "error": "gone"}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli._print_status([sparse, {"index": 2}], [0, 1])
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[0], "[0] MX Master 2S  (/dev/hidraw4)  disconnected")
        self.assertEqual(lines[1], "[1] Logitech mouse  (unknown path)")

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
