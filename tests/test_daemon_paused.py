"""maestrod waits quietly while Solaar or logiops owns HID++, then resumes."""

import contextlib
import io
import itertools
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput

from maestro import __main__ as cli
from maestro import mouse
from maestro.daemon import ipc, service
from maestro.daemon.actions import Actions
from maestro.daemon.config import ConfigFile
from maestro.daemon.profiles import resolve
from maestro.daemon.service import OWNER_RECHECK, Daemon, MouseSession, owner_problem

ROOT = Path(__file__).resolve().parents[1]
PROBLEM = "Solaar is running and controls the mouse. Close Solaar to use Maestro."


def fake_windows():
    return SimpleNamespace(
        connect=lambda: None,
        poll=lambda: {},
        dirty=lambda: False,
        close=lambda: None,
        error=None,
        socket=None,
    )


class PausedDaemonTests(unittest.TestCase):
    def test_problem_names_the_app_only(self):
        self.assertEqual(owner_problem("Solaar"), PROBLEM)
        self.assertEqual(
            owner_problem("logiops"),
            "logiops is running and controls the mouse. Stop logiops to use Maestro.",
        )

    def test_waits_without_hidpp_then_resumes_when_the_other_app_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            device = FakeDevice()
            device.channel.read_events = lambda: []
            output = FakeOutput()
            discovered, seen, checks = [], [], []
            # Solaar is open for the first two checks (start and one recheck).
            owners = itertools.chain(["Solaar", "Solaar"], itertools.repeat(None))

            def owner():
                checks.append(clock.now)
                return next(owners)

            def discover():
                discovered.append(clock.now)
                return [device]

            clock = SimpleNamespace(now=1000.0)

            def monotonic():
                clock.now += 0.5
                return clock.now

            daemon = None

            def poll(now):
                if daemon.paused_by:
                    status = daemon.handle({"op": "status"})
                    controls = daemon.handle({"op": "controls"})
                    with self.assertRaisesRegex(RuntimeError, "Close Solaar"):
                        daemon.handle({"op": "set", "device": 0, "settings": {"dpi": 1200}})
                    with self.assertRaisesRegex(RuntimeError, "Close Solaar"):
                        daemon.handle({"op": "release_buttons"})
                    seen.append((status, controls, list(device.calls)))
                if daemon.sessions:
                    daemon.stop = True

            server = SimpleNamespace(
                poll=poll, listener=SimpleNamespace(fileno=lambda: 123), close=lambda: None
            )
            daemon = Daemon(
                config,
                output_factory=lambda: output,
                discover=discover,
                windows=fake_windows(),
                server_factory=lambda handler: server,
            )
            with (
                patch.object(service, "check_other_owners", side_effect=owner),
                patch.object(service, "adopt_channels"),
                patch.object(service.time, "monotonic", side_effect=monotonic),
                patch.object(service.select, "select", return_value=([], [], [])),
                self.assertLogs("maestrod", level="INFO") as logs,
            ):
                daemon.run()

            self.assertTrue(seen, "the daemon never served requests while paused")
            for status, controls, calls in seen:
                self.assertEqual(status["devices"], [])
                self.assertEqual(status["paused_by"], "Solaar")
                self.assertEqual(status["problem"], PROBLEM)
                self.assertEqual(controls["devices"], [])
                self.assertEqual(controls["problem"], PROBLEM)
                self.assertEqual(calls, [])  # no HID++ while paused
            # Rechecked about every 15 seconds, and discovery only after Solaar left.
            self.assertGreaterEqual(len(checks), 3)
            self.assertAlmostEqual(checks[1] - checks[0], OWNER_RECHECK, delta=2)
            self.assertEqual(len(discovered), 1)
            self.assertGreater(discovered[0], checks[2] - 1)
            self.assertIsNone(daemon.paused_by)
            self.assertTrue(device.calls)  # normal discovery and configuration ran
            text = "\n".join(logs.output)
            self.assertIn(PROBLEM, text)
            self.assertEqual(text.count(PROBLEM), 1)  # logged once, not every recheck
            self.assertIn("Solaar is no longer running; resuming", text)
            self.assertNotRegex(text, r"PID|/usr/")

    def test_other_app_starting_mid_run_releases_mice_and_pauses(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
            daemon.actions = Actions(FakeOutput())
            self.addCleanup(daemon.close)
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            self.assertTrue(any(device.reporting.values()))
            with (
                patch.object(service, "check_other_owners", return_value="logiops"),
                self.assertLogs("maestrod", level="WARNING"),
            ):
                self.assertTrue(daemon.check_owner())
            self.assertEqual(set(device.reporting.values()), {0})  # diversions undone
            self.assertEqual((daemon.sessions, daemon.devices), ([], []))
            device.calls.clear()
            with patch.object(service, "check_other_owners", return_value="logiops"):
                self.assertTrue(daemon.check_owner())
            self.assertEqual(device.calls, [])
            self.assertIn("Stop logiops", daemon.handle({"op": "status"})["problem"])


class PausedCliTests(unittest.TestCase):
    paused = {
        "ok": True,
        "devices": [],
        "config_error": None,
        "window": {},
        "window_error": None,
        "sleeping": [],
        "scan_errors": [],
        "paused_by": "Solaar",
        "problem": PROBLEM,
    }

    def invoke(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
            patch.object(ipc, "request_if_running", return_value=self.paused),
            patch.object(ipc, "request", side_effect=AssertionError("no write while paused")),
            patch.object(mouse, "find_mice", side_effect=AssertionError("no hidraw")),
        ):
            code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_status_shows_the_problem_line(self):
        code, output, _ = self.invoke(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(output, f"Paused: {PROBLEM}\n")

    def test_status_json_stays_a_list_and_with_state_adds_the_reason(self):
        code, output, _ = self.invoke(["status", "--json"])
        self.assertEqual((code, json.loads(output)), (0, []))
        code, output, _ = self.invoke(["status", "--json", "--with-state"])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(output), {"devices": [], "paused_by": "Solaar", "problem": PROBLEM}
        )

    def test_writes_and_release_report_the_problem(self):
        for argv in (["dpi", "1200"], ["release-buttons"]):
            with self.subTest(argv=argv):
                code, output, error = self.invoke(argv)
                self.assertEqual((code, output), (1, ""))
                self.assertIn(PROBLEM, error)

    def test_controls_pass_the_problem_to_the_settings_app(self):
        response = {"ok": True, "daemon": True, "devices": [], **self.paused}
        stdout = io.StringIO()
        with (
            contextlib.redirect_stdout(stdout),
            patch.object(ipc, "request_if_running", return_value=response),
        ):
            self.assertEqual(cli.main(["controls", "--json"]), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual((result["paused_by"], result["problem"]), ("Solaar", PROBLEM))


class UnitFileTests(unittest.TestCase):
    def test_service_starts_are_bounded(self):
        text = (ROOT / "packaging/systemd/maestrod.service").read_text()
        values = dict(
            line.split("=", 1) for line in text.splitlines() if "=" in line and line[0] != "#"
        )
        self.assertEqual(values["Restart"], "on-failure")
        self.assertGreaterEqual(int(values["RestartSec"]), 3)
        self.assertLessEqual(int(values["StartLimitBurst"]), 10)
        self.assertGreaterEqual(int(values["StartLimitIntervalSec"]), 60)
        # Start limits are [Unit] settings; in [Service] systemd ignores them.
        unit = text.split("[Service]", 1)[0]
        self.assertIn("StartLimitIntervalSec=", unit)
        self.assertIn("StartLimitBurst=", unit)
        self.assertIn("journalctl --user -u maestrod", text)


if __name__ == "__main__":
    unittest.main()
