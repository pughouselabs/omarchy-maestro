"""A diversion left behind is explained and released only on request; nothing is reclaimed."""

import contextlib
import copy
import io
import json
import os
import signal
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput

from maestro import __main__ as cli
from maestro import hidpp, mouse
from maestro.daemon import ipc, ownership
from maestro.daemon.actions import Actions
from maestro.daemon.config import ConfigFile
from maestro.daemon.events import IDENTITY_PROBLEM
from maestro.daemon.ownership import (
    MAX_BYTES,
    RECORD_PROBLEM,
    DiversionLedger,
    RecordError,
    default_path,
    device_key,
    find_other_owner,
)
from maestro.daemon.profiles import resolve
from maestro.daemon.service import Daemon, MouseSession, check_other_owners, restore_hardware

GESTURE = 0xC3
BUSY = "The gesture button is held by another app (Solaar or logiops?)"
LEFTOVER = (
    "Maestro may have left the gesture button taken during an unexpected shutdown. "
    "Choose Release button to fix it."
)
TABS = {"thumb_wheel": {"mode": "tabs"}}
DIVERTED = 0x11  # temporary diversion with raw XY, as Maestro sets it for gestures


def writes(device, cid):
    return [
        params[2]
        for feature, function, params in device.calls
        if feature == hidpp.REPROG_CONTROLS_V4
        and function == 3
        and int.from_bytes(params[:2], "big") == cid
    ]


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "state" / "maestro" / "diversions.json"
        # No other mouse app is running unless a test says so.
        others = patch.object(ownership, "find_other_owner", return_value=None)
        self.others = others.start()
        self.addCleanup(others.stop)

    def ledger(self):
        return DiversionLedger(self.path)

    def session(self, device, ledger=None):
        session = MouseSession(device, Actions(FakeOutput()), ledger=ledger or self.ledger())
        self.addCleanup(session.close)
        return session

    def configure(self, session, raw=TABS):
        session.configure(resolve(raw, session.identity))

    def test_default_path_follows_state_home(self):
        self.assertEqual(
            default_path(),
            Path(os.environ["XDG_STATE_HOME"]) / "maestro" / "diversions.json",
        )

    def test_record_is_private_and_written_before_the_first_diversion(self):
        device = FakeDevice()
        ledger = self.ledger()
        original = device.call
        seen = []

        def call(feature, function, params=b"", timeout=1.0):
            if feature == hidpp.REPROG_CONTROLS_V4 and function == 3 and params[2] & 1:
                seen.append(ledger.get(device_key(device)))
            return original(feature, function, params, timeout)

        device.call = call
        session = self.session(device, ledger)
        self.configure(session)
        self.assertTrue(seen and seen[0] is not None)
        self.assertEqual(seen[0]["controls"], {GESTURE: (True, DIVERTED)})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        entry = ledger.get(device_key(device))
        self.assertEqual(entry["controls"], {GESTURE: (True, DIVERTED)})
        self.assertEqual(entry["thumb"], 1)
        text = self.path.read_text()
        self.assertNotIn("/dev/", text)
        # Only a hash of the unit ID is stored, never the ID itself.
        self.assertNotIn(device.unit.hex(), text.lower())
        self.assertEqual(len(device_key(device).rsplit("|", 1)[1]), 64)

    def test_matching_record_is_reported_and_never_reclaimed(self):
        # Maestro's record matches, but an unrecognized app could divert the
        # button the same way, so nothing is written until the user releases.
        device = FakeDevice()
        self.ledger().update(device_key(device), {GESTURE: (True, DIVERTED)}, None)
        device.reporting[GESTURE] = DIVERTED  # left behind by a crash or power loss
        session = self.session(device)
        with self.assertLogs("maestrod", level="WARNING") as logs:
            self.configure(session)
        self.assertTrue(session.online)
        self.assertEqual(session.problem, LEFTOVER)
        self.assertEqual(writes(device, GESTURE), [])
        self.assertEqual(device.reporting[GESTURE], DIVERTED)
        self.assertNotIn(GESTURE, session.diversion.owned)
        self.assertTrue(any("unexpected shutdown" in line for line in logs.output))
        # Still recorded, so a restart shows the same message.
        entry = self.ledger().get(device_key(device))
        self.assertEqual(entry["controls"], {GESTURE: (True, DIVERTED)})
        # Reconciling again writes nothing either.
        session.reconcile(resolve(TABS, session.identity))
        self.assertEqual(writes(device, GESTURE), [])
        # One explicit release frees it and Maestro takes it over.
        self.assertEqual(session.release_buttons(), ["gesture button"])
        self.assertIsNone(session.problem)
        self.assertEqual(session.diversion.owned, {GESTURE: True})
        self.assertEqual(writes(device, GESTURE)[:2], [0x22, 0x33])

    def test_record_survives_restart_and_hidraw_path_change(self):
        device = FakeDevice()
        first = MouseSession(device, Actions(FakeOutput()), ledger=self.ledger())
        self.configure(first)
        self.assertEqual(device.reporting[GESTURE], 0x11)
        # Simulated power loss: the daemon dies without cleanup, the mouse keeps
        # its diversion, and after boot the receiver appears at a new hidraw path.
        device.node = hidpp.HidrawNode("/dev/hidraw7", 3, 0x46D, 0xC52B, "receiver")
        device.calls.clear()
        second = self.session(device, DiversionLedger(self.path))
        with self.assertLogs("maestrod", level="WARNING"):
            self.configure(second)
        self.assertTrue(second.online)
        self.assertEqual(second.problem, LEFTOVER)
        self.assertEqual(writes(device, GESTURE), [])
        second.release_buttons()
        self.assertEqual(second.diversion.owned, {GESTURE: True})
        second.close()
        self.assertEqual(set(device.reporting.values()), {0})
        self.assertFalse(self.path.exists())

    def test_thumb_wheel_record_is_reported_and_never_reclaimed(self):
        device = FakeDevice()
        self.ledger().update(device_key(device), {}, 0x81)
        device.thumb_mode = [0x81, 1]
        session = self.session(device)
        with self.assertLogs("maestrod", level="WARNING"):
            self.configure(session)
        self.assertEqual(
            session.problem,
            "Maestro may have left the thumb wheel taken during an unexpected shutdown. "
            "Choose Release button to fix it.",
        )
        self.assertTrue(session.busy["thumb"].leftover)
        self.assertFalse(session.diversion.thumb_owned)
        self.assertEqual(device.thumb_mode, [0x81, 1])
        self.assertFalse(any(c[0] == hidpp.THUMB_WHEEL and c[1] == 2 for c in device.calls))
        session.release_buttons()
        self.assertTrue(session.diversion.thumb_owned)
        session.close()
        self.assertEqual(device.thumb_mode, [0x80, 1])
        self.assertFalse(self.path.exists())

    def test_without_record_another_owner_is_left_alone(self):
        for record in (None, "other-mouse"):
            with self.subTest(record=record):
                device = FakeDevice()
                ledger = DiversionLedger(self.root / f"{record}.json")
                if record:
                    # An identical mouse in the same slot of an identical receiver.
                    other = FakeDevice()
                    other.unit = b"\x01\x02\x03\x04"
                    ledger.update(device_key(other), {GESTURE: (True, DIVERTED)}, 1)
                device.reporting[GESTURE] = DIVERTED
                device.thumb_mode = [1, 1]
                session = self.session(device, ledger)
                self.configure(session)
                self.assertTrue(session.online and session.verified)
                self.assertTrue(session.problem.startswith(BUSY))
                self.assertIn(
                    "The thumb wheel is held by another app (Solaar or logiops?). "
                    "Close it, or turn the mouse off and on. If no other app is running, "
                    "choose Release button in Maestro settings.",
                    session.errors,
                )
                self.assertEqual(writes(device, GESTURE), [])
                self.assertNotIn(GESTURE, session.diversion.owned)
                self.assertFalse(session.diversion.thumb_owned)
                self.assertEqual(device.reporting[GESTURE], 0x11)
                self.assertEqual(device.thumb_mode, [1, 1])
                # Other buttons keep working.
                self.configure(
                    session, {"buttons": {"middle": {"type": "mouse", "button": "middle"}}}
                )
                self.assertIn(0x52, session.diversion.owned)
                session.close()

    def test_busy_control_is_retried_once_the_other_app_lets_go(self):
        device = FakeDevice()
        device.reporting[GESTURE] = 0x11
        session = self.session(device)
        options = resolve(TABS, session.identity)
        session.configure(options)
        self.assertIsNotNone(session.problem)
        session.reconcile(options)
        self.assertIsNotNone(session.problem)
        self.assertEqual(writes(device, GESTURE), [])
        device.reporting[GESTURE] = 0
        session.reconcile(options)
        self.assertIsNone(session.problem)
        self.assertEqual(session.diversion.owned, {GESTURE: True})

    def test_malformed_or_oversized_record_is_ignored(self):
        device = FakeDevice()
        key = device_key(device)
        bad = {
            "garbage": b"{not json",
            "wrong shape": json.dumps({"version": 1, "devices": []}).encode(),
            "bad entry": json.dumps(
                {"version": 2, "devices": {key: {"controls": {"0x00c3": "yes"}}}}
            ).encode(),
            "oversized": json.dumps(
                {
                    "version": 2,
                    "devices": {key: {"controls": {"0x00c3": {"raw_xy": True, "flags": 17}}}},
                    "pad": "x" * MAX_BYTES,
                }
            ).encode(),
            "older format": json.dumps(
                {"version": 1, "devices": {key: {"controls": {"0x00c3": True}}}}
            ).encode(),
            "huge timestamp": self.record(key, updated="1" + "0" * 400),
            "infinite timestamp": self.record(key, updated="Infinity"),
            "not a number": self.record(key, updated="NaN"),
            "negative timestamp": self.record(key, updated="-1"),
            "boolean timestamp": self.record(key, updated="true"),
            "bad control id": self.record(key, cid="0xzzzz"),
            "short control id": self.record(key, cid="0xc3"),
            "huge flags": self.record(key, flags="4096"),
            "boolean flags": self.record(key, flags="true"),
            "bad thumb": self.record(key, thumb="-1"),
            "bad key": self.record("../../etc", flags="17"),
            "deep nesting": b"[" * 20000 + b"]" * 20000,
        }
        for name, data in bad.items():
            with self.subTest(name=name):
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(data)
                device = FakeDevice()
                device.reporting[GESTURE] = 0x11
                ledger = self.ledger()
                with self.assertLogs("maestrod", level="WARNING") as logs:
                    self.assertEqual(ledger.load(), {})
                self.assertIn("ignoring", logs.output[0])
                session = self.session(device, ledger)
                self.configure(session)
                self.assertTrue(session.problem.startswith(BUSY))
                self.assertEqual(writes(device, GESTURE), [])
                session.close()

    @staticmethod
    def record(key, updated="1.5", cid="0x00c3", flags="17", thumb="null"):
        return (
            f'{{"version": 2, "devices": {{"{key}": {{"updated": {updated}, "thumb": {thumb}, '
            f'"controls": {{"{cid}": {{"raw_xy": true, "flags": {flags}}}}}}}}}}}'
        ).encode()

    def test_record_is_bounded(self):
        ledger = self.ledger()
        controls = {cid: (True, 0x11) for cid in range(16)}
        for unit in range(40):
            device = FakeDevice()
            device.unit = (unit + 1).to_bytes(4, "big")
            ledger.update(device_key(device), controls, 0x81)
        self.assertLessEqual(len(ledger.load()), 32)
        self.assertLess(self.path.stat().st_size, MAX_BYTES)
        with self.assertRaises(RecordError):
            ledger.update(device_key(FakeDevice()), {cid: (True, 1) for cid in range(17)}, None)

    def test_write_enforces_the_byte_limit(self):
        ledger = self.ledger()
        key = device_key(FakeDevice())
        ledger.update(key, {GESTURE: (True, DIVERTED)}, None)
        before = self.path.read_bytes()
        with (
            patch.object(ownership, "MAX_BYTES", 64),
            self.assertRaisesRegex(RecordError, "size limit"),
        ):
            ledger.update(key, {GESTURE: (False, 1)}, None)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_daemon_stays_up_reports_status_and_clears_record_on_sigterm(self):
        config = ConfigFile(self.root / "config.json")
        config.raw = dict(TABS)
        device = FakeDevice()
        device.reporting[GESTURE] = 0x11
        output = FakeOutput()
        windows = SimpleNamespace(
            connect=lambda: None,
            poll=lambda: {},
            dirty=lambda: False,
            close=lambda: None,
            error=None,
            socket=None,
        )
        handlers, seen = {}, {}

        def install(signum, callback):
            previous = handlers.get(signum, signal.SIG_DFL)
            handlers[signum] = callback
            return previous

        daemon = None

        def poll(now):
            status = daemon.handle({"op": "status"})["devices"][0]
            seen["status"] = status
            seen["controls"] = daemon.handle({"op": "controls"})["devices"][0]
            seen["set"] = daemon.handle({"op": "set", "settings": {"dpi": 1200}})
            seen["record"] = daemon.ledger.get(device_key(device))
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        server = SimpleNamespace(
            poll=poll, listener=SimpleNamespace(fileno=lambda: 123), close=lambda: None
        )
        daemon = Daemon(
            config,
            output_factory=lambda: output,
            discover=lambda: [device],
            windows=windows,
            server_factory=lambda handler: server,
            ledger=self.ledger(),
        )
        with (
            patch("maestro.daemon.service.adopt_channels"),
            patch("maestro.daemon.service.check_other_owners", return_value=None),
            patch("maestro.daemon.service.signal.signal", side_effect=install),
            patch("maestro.daemon.service.select.select", return_value=([], [], [])),
            patch.object(daemon, "process_events"),
        ):
            daemon.run()
        self.assertTrue(seen["status"]["online"])
        self.assertTrue(seen["status"]["problem"].startswith(BUSY))
        self.assertTrue(seen["controls"]["problem"].startswith(BUSY))
        self.assertTrue(seen["set"]["ok"])
        self.assertEqual(device.dpi, 1200)
        # The busy gesture button was never ours; the thumb wheel was.
        self.assertEqual(seen["record"]["controls"], {})
        self.assertEqual(seen["record"]["thumb"], 1)
        self.assertTrue(seen["status"]["release_available"])
        self.assertEqual(writes(device, GESTURE), [])
        self.assertEqual(device.reporting[GESTURE], 0x11)
        self.assertEqual(device.thumb_mode, [0, 1])
        self.assertFalse(self.path.exists())

    def test_clean_close_clears_the_record(self):
        device = FakeDevice()
        ledger = self.ledger()
        session = self.session(device, ledger)
        self.configure(session)
        self.assertIsNotNone(ledger.get(device_key(device)))
        self.assertEqual(session.close(), [])
        self.assertIsNone(ledger.get(device_key(device)))
        self.assertFalse(self.path.exists())

    def test_failed_undivert_keeps_the_record_for_the_next_run(self):
        device = FakeDevice()
        ledger = self.ledger()
        session = self.session(device, ledger)
        self.configure(session)
        original = session.diversion._set

        def fail(cid, enabled, raw_xy):
            if not enabled:
                raise hidpp.Timeout("mouse went away")
            return original(cid, enabled, raw_xy)

        session.diversion._set = fail
        self.assertTrue(session.close())
        self.assertEqual(ledger.get(device_key(device))["controls"], {GESTURE: (True, DIVERTED)})
        session.diversion._set = original
        session.close()
        self.assertIsNone(ledger.get(device_key(device)))

    # --- unique identity -------------------------------------------------

    def test_identical_mice_have_separate_records(self):
        first, second = FakeDevice(), FakeDevice()
        second.unit = b"\x01\x02\x03\x04"
        second.node = hidpp.HidrawNode("/dev/fake2", 3, 0x46D, 0xC52B, "receiver")
        self.assertNotEqual(device_key(first), device_key(second))
        ledger = self.ledger()
        one = self.session(first, ledger)
        self.configure(one)
        # The second mouse shows the same leftover flags, but it is not ours.
        second.reporting[GESTURE] = DIVERTED
        two = self.session(second, ledger)
        self.configure(two)
        self.assertTrue(two.problem.startswith(BUSY))
        self.assertEqual(writes(second, GESTURE), [])
        # Cleaning up the second mouse keeps the first mouse's record.
        two.close()
        self.assertEqual(ledger.get(device_key(first))["controls"], {GESTURE: (True, DIVERTED)})
        one.close()
        self.assertIsNone(ledger.get(device_key(first)))

    def test_without_a_unit_id_nothing_is_recorded_or_reclaimed(self):
        for case in ("blank", "all ones", "missing feature", "read fails"):
            with self.subTest(case=case):
                device = FakeDevice()
                if case == "blank":
                    device.unit = b"\0\0\0\0"
                elif case == "all ones":
                    device.unit = b"\xff\xff\xff\xff"
                elif case == "missing feature":
                    del device.features[hidpp.FW_VERSION]
                else:
                    original = device.call

                    def call(feature, function, params=b"", timeout=1.0, original=original):
                        if feature == hidpp.FW_VERSION:
                            raise hidpp.Timeout("no reply")
                        return original(feature, function, params, timeout)

                    device.call = call
                self.assertIsNone(device_key(device))
                ledger = DiversionLedger(self.root / f"{case}.json")
                session = self.session(device, ledger)
                self.configure(session)
                # Such a mouse is read-only: nothing is diverted or recorded.
                self.assertEqual(session.diversion.owned, {})
                self.assertEqual(session.problem, IDENTITY_PROBLEM)
                self.assertEqual(self.hardware_writes(device), [])
                self.assertFalse(ledger.path.exists())
                session.close()
                # A leftover on such a mouse is never released either.
                device.reporting[GESTURE] = DIVERTED
                again = self.session(device, ledger)
                self.configure(again)
                self.assertEqual(again.problem, IDENTITY_PROBLEM)
                with self.assertRaises(hidpp.NoResponse):
                    again.release_buttons()
                again.close()
                self.assertEqual(self.hardware_writes(device), [])
                self.assertEqual(device.reporting[GESTURE], DIVERTED)

    def test_diagnose_never_reads_or_reports_the_unit_id(self):
        device = FakeDevice()
        device.feature_details = lambda: []
        device.version = (4, 5)
        report = json.dumps(mouse.diagnose(device))
        self.assertNotIn(device.unit.hex(), report.lower())
        self.assertNotIn(device_key(device).rsplit("|", 1)[1], report)
        diagnose_calls = [c for c in device.calls[:-1] if c[0] == hidpp.FW_VERSION]
        self.assertEqual(diagnose_calls, [])

    # --- no automatic reclaim ------------------------------------------------

    def test_changed_flags_are_reported_as_another_app(self):
        for current in (0x01, 0x13, 0x31):
            with self.subTest(current=hex(current)):
                device = FakeDevice()
                ledger = DiversionLedger(self.root / f"changed-{current}.json")
                ledger.update(device_key(device), {GESTURE: (True, DIVERTED)}, None)
                # Another app diverted the button with different reporting flags.
                device.reporting[GESTURE] = current
                session = self.session(device, ledger)
                self.configure(session)
                self.assertTrue(session.problem.startswith(BUSY))
                self.assertIn("Release button", session.problem)
                self.assertEqual(writes(device, GESTURE), [])
                self.assertEqual(device.reporting[GESTURE], current)
                session.close()
                self.assertEqual(device.reporting[GESTURE], current)

    def test_changed_thumb_flags_are_another_app(self):
        device = FakeDevice()
        self.ledger().update(device_key(device), {}, 0x81)
        device.thumb_mode = [0x03, 1]
        session = self.session(device)
        self.configure(session)
        self.assertIn("thumb", session.busy)
        self.assertFalse(session.busy["thumb"].leftover)
        self.assertEqual(device.thumb_mode, [0x03, 1])

    def test_startup_never_scans_processes_or_writes_a_leftover(self):
        device = FakeDevice()
        self.ledger().update(device_key(device), {GESTURE: (True, DIVERTED)}, 0x81)
        device.reporting[GESTURE] = DIVERTED
        device.thumb_mode = [0x81, 1]
        session = self.session(device)
        with self.assertLogs("maestrod", level="WARNING"):
            self.configure(session)
        self.others.assert_not_called()
        self.assertEqual(writes(device, GESTURE), [])
        self.assertEqual(device.thumb_mode, [0x81, 1])
        self.assertEqual(set(session.busy), {GESTURE, "thumb"})
        self.assertTrue(all(exc.leftover for exc in session.busy.values()))

    def test_explicit_release_frees_the_button_and_maestro_takes_over(self):
        device = FakeDevice()
        self.ledger().update(device_key(device), {GESTURE: (True, DIVERTED)}, None)
        device.reporting[GESTURE] = 0x13
        device.thumb_mode = [0x01, 1]
        session = self.session(device)
        self.configure(session)
        self.assertIsNotNone(session.problem)
        released = session.release_buttons()
        self.assertEqual(released, ["gesture button", "thumb wheel"])
        self.assertIsNone(session.problem)
        self.assertEqual(session.diversion.owned, {GESTURE: True})
        self.assertTrue(session.diversion.thumb_owned)
        # Persistent bits (0x02 here) are never written.
        self.assertEqual(device.reporting[GESTURE] & 0x02, 0x02)
        self.assertEqual(session.release_buttons(), [])

    def test_release_buttons_ipc_and_cli_with_the_daemon(self):
        config = ConfigFile(self.root / "config.json")
        config.raw = dict(TABS)
        daemon = Daemon(config, ledger=self.ledger())
        daemon.actions = Actions(FakeOutput())
        self.addCleanup(daemon.close)
        device = FakeDevice()
        device.reporting[GESTURE] = DIVERTED
        session = MouseSession(device, daemon.actions, ledger=daemon.ledger)
        daemon.sessions.append(session)
        daemon.devices.append(device)
        session.configure(daemon.options(session))
        status = daemon.handle({"op": "status"})["devices"][0]
        self.assertTrue(status["release_available"])
        self.assertTrue(daemon.handle({"op": "controls"})["devices"][0]["release_available"])
        with self.assertRaises(ValueError):
            daemon.handle({"op": "release_buttons", "device": 5})

        def exchange(message):
            return json.loads(json.dumps(daemon.handle(json.loads(json.dumps(message)))))

        out = io.StringIO()
        with (
            patch.object(ipc, "request_if_running", side_effect=exchange),
            patch.object(ipc, "request", side_effect=exchange),
            patch.object(mouse, "find_mice") as direct,
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(cli.main(["release-buttons", "--mouse", "0"]), 0)
        direct.assert_not_called()
        self.assertEqual(out.getvalue(), "Released the gesture button on MX Master 2S (mouse 0).\n")
        self.assertIsNone(session.problem)
        self.assertEqual(session.diversion.owned, {GESTURE: True})
        self.assertFalse(daemon.handle({"op": "status"})["devices"][0]["release_available"])

    def test_release_buttons_cli_without_the_daemon(self):
        device = FakeDevice()
        DiversionLedger().update(device_key(device), {GESTURE: (True, DIVERTED)}, None)
        device.reporting[GESTURE] = DIVERTED
        device.reporting[0x53] = 0x01
        out = io.StringIO()
        with (
            patch.object(ipc, "request_if_running", return_value=None),
            patch.object(mouse, "find_mice", return_value=[device]),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(cli.main(["release-buttons", "--json"]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual(
            result["devices"],
            [{"device": 0, "model": "MX Master 2S", "released": ["back button", "gesture button"]}],
        )
        self.assertEqual(set(device.reporting.values()), {0})
        self.assertIsNone(DiversionLedger().get(device_key(device)))

    # --- release targets only the chosen mouse ------------------------------

    def two_mice(self):
        first, second = FakeDevice(), FakeDevice()
        second.unit = b"\x01\x02\x03\x04"
        second.node = hidpp.HidrawNode("/dev/fake2", 3, 0x46D, 0xC52B, "receiver")
        for device in (first, second):
            device.reporting[GESTURE] = DIVERTED
            device.thumb_mode = [0x01, 1]
        return first, second

    def hardware_writes(self, device):
        return [call for call in device.calls if hidpp.is_write(*call[:2])]

    def test_release_refuses_a_mouse_that_moved_after_status(self):
        for use_app_selector in (False, True):
            with self.subTest(app=use_app_selector):
                config = ConfigFile(self.root / f"config-{use_app_selector}.json")
                config.raw = dict(TABS)
                daemon = Daemon(
                    config, ledger=DiversionLedger(self.root / f"{use_app_selector}.json")
                )
                daemon.actions = Actions(FakeOutput())
                self.addCleanup(daemon.close)
                first, second = self.two_mice()
                for device in (first, second):
                    session = MouseSession(device, daemon.actions, ledger=daemon.ledger)
                    daemon.sessions.append(session)
                    daemon.devices.append(device)
                    session.configure(daemon.options(session))
                chosen = daemon.handle({"op": "controls"})["devices"][0]["selector"]
                self.assertEqual(chosen["path"], "/dev/fake")
                self.assertIsNotNone(chosen["unit"])
                for device in (first, second):
                    device.calls.clear()

                def status_then_reorder(message, daemon=daemon, reorder=not use_app_selector):
                    response = json.loads(json.dumps(daemon.handle(message)))
                    if reorder:
                        daemon.devices.reverse()  # discovery changed after status
                    return response

                def exchange(message, daemon=daemon):
                    return json.loads(json.dumps(daemon.handle(json.loads(json.dumps(message)))))

                if use_app_selector:
                    daemon.devices.reverse()  # changed before the app's request
                argv = ["release-buttons", "--mouse", "0"]
                if use_app_selector:
                    argv += ["--selector", json.dumps(chosen)]
                err = io.StringIO()
                with (
                    patch.object(ipc, "request_if_running", side_effect=status_then_reorder),
                    patch.object(ipc, "request", side_effect=exchange),
                    patch.object(mouse, "find_mice") as direct,
                    contextlib.redirect_stderr(err),
                ):
                    self.assertEqual(cli.main(argv), 2)
                direct.assert_not_called()
                self.assertIn("device identity changed", err.getvalue())
                self.assertEqual(self.hardware_writes(first), [])
                self.assertEqual(self.hardware_writes(second), [])
                self.assertEqual(first.reporting[GESTURE], DIVERTED)
                self.assertEqual(second.reporting[GESTURE], DIVERTED)

    def test_release_ipc_needs_a_matching_selector(self):
        config = ConfigFile(self.root / "config.json")
        config.raw = dict(TABS)
        daemon = Daemon(config, ledger=self.ledger())
        daemon.actions = Actions(FakeOutput())
        self.addCleanup(daemon.close)
        first, second = self.two_mice()
        for device in (first, second):
            session = MouseSession(device, daemon.actions, ledger=daemon.ledger)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(daemon.options(session))
        selectors = [d["selector"] for d in daemon.handle({"op": "controls"})["devices"]]
        self.assertNotEqual(selectors[0], selectors[1])
        for device in (first, second):
            device.calls.clear()
        bad = (
            {"op": "release_buttons", "device": 0},
            {"op": "release_buttons", "device": 0, "selector": selectors[1]},
            {"op": "release_buttons", "device": 0, "selector": dict(selectors[0], unit="0" * 16)},
            {"op": "release_buttons", "device": 0, "selector": {"path": "/dev/fake"}},
            {"op": "release_buttons", "selector": selectors[0]},
        )
        for message in bad:
            with self.subTest(message=message), self.assertRaises(ValueError):
                daemon.handle(message)
        self.assertEqual(self.hardware_writes(first) + self.hardware_writes(second), [])
        result = daemon.handle({"op": "release_buttons", "device": 1, "selector": selectors[1]})
        self.assertEqual(result["devices"][0]["device"], 1)
        self.assertEqual(self.hardware_writes(first), [])
        self.assertNotEqual(self.hardware_writes(second), [])

    def test_offline_release_refuses_a_changed_mouse(self):
        first, second = self.two_mice()
        chosen = {
            "path": first.node.path,
            "index": first.index,
            "model": first.model,
            "unit": ownership.selector_tag(device_key(first)),
        }
        for device in (first, second):
            device.calls.clear()
        err = io.StringIO()
        with (
            patch.object(ipc, "request_if_running", return_value=None),
            patch.object(mouse, "find_mice", return_value=[second, first]),
            contextlib.redirect_stderr(err),
        ):
            argv = ["release-buttons", "--mouse", "0", "--selector", json.dumps(chosen)]
            self.assertEqual(cli.main(argv), 2)
        self.assertIn("device identity changed", err.getvalue())
        self.assertEqual(self.hardware_writes(first) + self.hardware_writes(second), [])
        out = io.StringIO()
        with (
            patch.object(ipc, "request_if_running", return_value=None),
            patch.object(mouse, "find_mice", return_value=[second, first]),
            contextlib.redirect_stdout(out),
        ):
            argv = ["release-buttons", "--mouse", "1", "--selector", json.dumps(chosen), "--json"]
            self.assertEqual(cli.main(argv), 0)
        self.assertEqual(self.hardware_writes(second), [])
        self.assertEqual(first.reporting[GESTURE], 0)

    # --- a same-model mouse paired into the same receiver slot ---------------

    def swap_daemon(self, raw=TABS):
        """Mouse A in receiver slot 1, then a same-model mouse B paired into it.

        The old Device object addresses the slot, so after the swap its calls
        reach B. Every write B receives lands in ``b.calls``.
        """
        config = ConfigFile(self.root / "config.json")
        config.raw = copy.deepcopy(raw)
        a, b = FakeDevice(), FakeDevice()
        b.unit = b"\x01\x02\x03\x04"
        b.reporting[GESTURE] = DIVERTED  # something a release would clear
        b.thumb_mode = [0x01, 1]
        slot = [a]
        daemon = Daemon(config, discover=lambda: list(slot), ledger=self.ledger())
        daemon.actions = Actions(FakeOutput())
        self.addCleanup(daemon.close)
        daemon.discover_devices()
        chosen = daemon.handle({"op": "controls"})["devices"][0]["selector"]
        self.assertEqual(chosen["unit"], ownership.selector_tag(device_key(a)))
        self.assertEqual(daemon.sessions[0].diversion.owned, {GESTURE: True})

        def swap():
            a.route = b  # A's Device object now reaches B
            slot[0] = b
            b.calls.clear()

        return daemon, a, b, chosen, swap

    def test_release_with_a_stale_selector_never_writes_to_a_replacement(self):
        for discover_first in (False, True):
            with self.subTest(discovery=discover_first):
                daemon, a, b, chosen, swap = self.swap_daemon()
                key_a = device_key(a)
                swap()
                if discover_first:
                    daemon.discover_devices()
                    # A's session is gone; B has its own, with nothing of A's.
                    self.assertEqual(len(daemon.sessions), 1)
                    session = daemon.sessions[0]
                    self.assertIs(session.device, b)
                    self.assertEqual(
                        session.diversion.unit_key, ownership.selector_tag(device_key(b))
                    )
                    self.assertNotIn(GESTURE, session.diversion.owned)
                    self.assertEqual(daemon.retired_sessions, [])
                    # B's gesture button belongs to whoever diverted it.
                    self.assertEqual(writes(b, GESTURE), [])
                    self.assertEqual(b.reporting[GESTURE], DIVERTED)
                    b.calls.clear()
                with self.assertRaisesRegex(ValueError, "device identity changed"):
                    daemon.handle({"op": "release_buttons", "device": 0, "selector": chosen})
                self.assertEqual(self.hardware_writes(b), [])
                self.assertEqual(b.reporting[GESTURE], DIVERTED)
                self.assertEqual(b.thumb_mode[0] & 1, 1)
                # Stopping the daemon writes nothing to B on A's behalf either.
                if not discover_first:
                    daemon.close()
                    self.assertEqual(self.hardware_writes(b), [])
                    # A's record stays, so A is still reported if it returns.
                    self.assertIsNotNone(self.ledger().get(key_a))

    def test_a_mouse_whose_unit_id_becomes_unreadable_cannot_be_released(self):
        daemon, a, b, chosen, swap = self.swap_daemon()
        a.reporting[GESTURE] = 0x13  # something a release would clear
        a.unit = b"\0\0\0\0"
        a.calls.clear()
        with self.assertRaisesRegex(hidpp.NoResponse, "unit ID"):
            daemon.handle({"op": "release_buttons", "device": 0, "selector": chosen})
        self.assertEqual(self.hardware_writes(a), [])
        self.assertEqual(a.reporting[GESTURE], 0x13)
        # Discovery holds the session without writing and starts no new one.
        daemon.discover_devices()
        self.assertEqual(daemon.sessions, [])
        self.assertEqual(len(daemon.retired_sessions), 1)
        self.assertEqual(self.hardware_writes(a), [])
        # The same unit ID reading back again resumes the original session.
        a.unit = FakeDevice().unit
        daemon.discover_devices()
        self.assertEqual(daemon.retired_sessions, [])
        self.assertEqual(daemon.sessions[0].diversion.owned, {GESTURE: True})
        # Without the daemon, an unreadable unit ID is refused the same way.
        daemon.close()
        a.unit = b"\0\0\0\0"
        a.calls.clear()
        err = io.StringIO()
        with (
            patch.object(ipc, "request_if_running", return_value=None),
            patch.object(mouse, "find_mice", return_value=[a]),
            contextlib.redirect_stderr(err),
        ):
            argv = ["release-buttons", "--mouse", "0", "--selector", json.dumps(chosen)]
            self.assertEqual(cli.main(argv), 2)
        self.assertIn("device identity changed", err.getvalue())
        self.assertEqual(self.hardware_writes(a), [])

    def test_shutdown_skips_a_held_session_whose_unit_id_is_unreadable(self):
        daemon, a, b, chosen, swap = self.swap_daemon()
        key_a = device_key(a)
        a.unit = b"\0\0\0\0"
        daemon.discover_devices()
        self.assertEqual(len(daemon.retired_sessions), 1)
        a.calls.clear()
        with self.assertLogs("maestrod", level="ERROR"):
            daemon.close()
        self.assertEqual(self.hardware_writes(a), [])
        self.assertIsNotNone(self.ledger().get(key_a))

    # --- one rule: every write first confirms the live unit ID ---------------

    def unit_reads(self, device):
        return [call for call in device.calls if call[0] == hidpp.FW_VERSION]

    def test_shutdown_never_writes_to_a_replacement_whose_unit_id_is_unreadable(self):
        for try_release in (False, True):
            with self.subTest(release_first=try_release):
                daemon, a, b, chosen, swap = self.swap_daemon()
                key_a = device_key(a)
                swap()
                b.unit = b"\0\0\0\0"
                if try_release:
                    with self.assertRaisesRegex(hidpp.NoResponse, "unit ID"):
                        daemon.handle({"op": "release_buttons", "device": 0, "selector": chosen})
                with self.assertLogs("maestrod", level="ERROR"):
                    daemon.close()
                self.assertEqual(self.hardware_writes(b), [])
                self.assertEqual(b.reporting[GESTURE], DIVERTED)
                self.assertEqual(b.thumb_mode[0] & 1, 1)
                # A's record stays, so A is still reported if it returns.
                self.assertEqual(self.ledger().get(key_a)["controls"], {GESTURE: (True, DIVERTED)})

    def test_unreadable_unit_id_holds_the_slot_across_scans(self):
        daemon, a, b, chosen, swap = self.swap_daemon()
        swap()
        b.unit = b"\0\0\0\0"
        for _ in range(3):
            daemon.discover_devices()
            self.assertEqual(daemon.sessions, [])
            self.assertEqual(len(daemon.retired_sessions), 1)
            self.assertEqual(self.hardware_writes(b), [])
            status = daemon.handle({"op": "status"})["devices"][0]
            self.assertEqual(status["problem"], IDENTITY_PROBLEM)
        # Once B's own unit ID reads, it gets a fresh session with nothing of A's.
        b.unit = b"\x01\x02\x03\x04"
        daemon.discover_devices()
        self.assertEqual(len(daemon.sessions), 1)
        self.assertIs(daemon.sessions[0].device, b)
        self.assertNotIn(GESTURE, daemon.sessions[0].diversion.owned)
        self.assertEqual(writes(b, GESTURE), [])

    def test_settings_writes_never_reach_a_replacement(self):
        raw = {**TABS, "settings": {"dpi": 1600}}
        for path in ("reconcile", "set", "rollback", "config rollback"):
            with self.subTest(path=path):
                daemon, a, b, chosen, swap = self.swap_daemon(raw)
                self.assertEqual(a.dpi, 1600)
                session = daemon.sessions[0]
                if path == "reconcile":
                    swap()
                    session.reconcile(daemon.options(session))
                    self.assertEqual(session.identity_state, "changed")
                elif path == "set":
                    swap()
                    with self.assertRaisesRegex(hidpp.NoResponse, "different mouse"):
                        daemon.handle({"op": "set", "settings": {"dpi": 1200}})
                    self.assertEqual(daemon.config.raw["settings"], {"dpi": 1600})
                elif path == "rollback":
                    # A takes the new value, then B replaces A before the rollback.
                    def save_then_swap(swap=swap, **kwargs):
                        swap()
                        raise OSError("disk full")

                    with (
                        patch.object(daemon.config, "save_device_settings", save_then_swap),
                        self.assertLogs("maestrod", level="ERROR"),
                        self.assertRaisesRegex(OSError, "disk full"),
                    ):
                        daemon.handle({"op": "set", "settings": {"dpi": 1200}})
                    self.assertEqual(a.dpi, 1200)
                else:
                    snapshots = [(session, {"dpi": 1600})]
                    swap()
                    errors = restore_hardware(snapshots)
                    self.assertTrue(errors and "skipped" in errors[0], errors)
                self.assertEqual(self.hardware_writes(b), [])
                self.assertEqual(b.dpi, 1000)
                self.assertTrue(self.unit_reads(b))

    def test_shutdown_stops_when_a_replacement_arrives_after_a_cleanup_timeout(self):
        # A answers the identity check, its first cleanup write times out,
        # then B replaces A. Nothing reaches B, and A's record is kept.
        for unit in (b"\x01\x02\x03\x04", b"\0\0\0\0"):
            with self.subTest(b_unit=unit):
                daemon, a, b, chosen, swap = self.swap_daemon()
                key_a = device_key(a)
                b.unit = unit
                original = a.answer

                def time_out_then_swap(feature, function, params=b"", original=original, swap=swap):
                    if hidpp.is_write(feature, function):
                        swap()
                        raise hidpp.Timeout("lost acknowledgement")
                    return original(feature, function, params)

                a.answer = time_out_then_swap
                with self.assertLogs("maestrod", level="ERROR"):
                    daemon.close()
                self.assertEqual(self.hardware_writes(b), [])
                self.assertTrue(self.unit_reads(b))
                self.assertEqual(b.reporting[GESTURE], DIVERTED)
                self.assertEqual(b.thumb_mode[0] & 1, 1)
                self.assertEqual(self.ledger().get(key_a)["controls"], {GESTURE: (True, DIVERTED)})

    def test_a_settings_batch_stops_at_a_swap_in_the_middle(self):
        raw = {**TABS, "settings": {"dpi": 1600}}
        daemon, a, b, chosen, swap = self.swap_daemon(raw)
        original = a.answer

        def swap_after_dpi(feature, function, params=b""):
            data = original(feature, function, params)
            if feature == hidpp.ADJUSTABLE_DPI and function == 3:
                swap()
            return data

        a.answer = swap_after_dpi
        with (
            self.assertLogs("maestrod", level="ERROR"),
            self.assertRaises((hidpp.NoResponse, ValueError)),
        ):
            daemon.handle({"op": "set", "settings": {"dpi": 1200, "invert": True}})
        self.assertEqual(a.dpi, 1200)
        self.assertEqual(self.hardware_writes(b), [])
        self.assertEqual(b.wheel_flags, 2)
        self.assertEqual(b.dpi, 1000)
        self.assertTrue(self.unit_reads(b))

    def test_a_mouse_with_a_readable_unit_id_works_as_before(self):
        raw = {**TABS, "settings": {"dpi": 1600}}
        daemon, a, b, chosen, swap = self.swap_daemon(raw)
        key_a = device_key(a)
        session = daemon.sessions[0]
        self.assertEqual(a.dpi, 1600)
        self.assertEqual(session.diversion.owned, {GESTURE: True})
        self.assertIsNone(session.problem)
        # A reconcile with nothing to change reads no unit ID at all.
        a.calls.clear()
        session.reconcile(daemon.options(session))
        self.assertEqual(self.hardware_writes(a), [])
        self.assertEqual(self.unit_reads(a), [])
        self.assertTrue(session.online and session.verified)
        # A settings change is written, with a unit ID read before each write.
        a.calls.clear()
        result = daemon.handle({"op": "set", "settings": {"dpi": 1200}})
        self.assertEqual(result["status"]["dpi"]["current"], 1200)
        self.assertEqual(a.dpi, 1200)
        self.assertLessEqual(len(self.unit_reads(a)), 3)
        # Discovery keeps the session, and shutdown releases what it diverted.
        daemon.discover_devices()
        self.assertIs(daemon.sessions[0], session)
        daemon.close()
        self.assertEqual(a.reporting[GESTURE], 0)
        self.assertEqual(a.thumb_mode[0] & 1, 0)
        self.assertIsNone(self.ledger().get(key_a))

    # --- durable persistence ------------------------------------------------

    def test_failed_save_never_diverts_and_reports_status(self):
        device = FakeDevice()
        ledger = self.ledger()
        session = self.session(device, ledger)
        with (
            patch.object(ledger, "_write", side_effect=OSError(28, "No space left on device")),
            self.assertLogs("maestrod", level="WARNING"),
        ):
            self.configure(session)
        self.assertEqual(session.problem, RECORD_PROBLEM)
        self.assertEqual(writes(device, GESTURE), [])
        self.assertEqual(device.reporting[GESTURE], 0)
        self.assertEqual(device.thumb_mode, [0, 1])
        self.assertEqual(session.diversion.owned, {})
        self.assertFalse(session.diversion.thumb_owned)
        self.assertTrue(session.online)
        # Retried once the record can be saved again.
        session.reconcile(resolve(TABS, session.identity))
        self.assertIsNone(session.problem)
        self.assertEqual(session.diversion.owned, {GESTURE: True})
        self.assertEqual(ledger.get(device_key(device))["controls"], {GESTURE: (True, DIVERTED)})

    def test_unwritable_state_directory_blocks_diversion(self):
        self.path.parent.parent.mkdir(parents=True)
        self.path.parent.symlink_to(self.root)  # not a private directory
        device = FakeDevice()
        session = self.session(device)
        with self.assertLogs("maestrod", level="WARNING"):
            self.configure(session)
        self.assertEqual(session.problem, RECORD_PROBLEM)
        self.assertEqual(writes(device, GESTURE), [])

    def test_failed_cleanup_save_is_logged_and_retried(self):
        device = FakeDevice()
        ledger = self.ledger()
        session = self.session(device, ledger)
        self.configure(session)
        with (
            patch.object(ledger, "_write", side_effect=OSError(5, "I/O error")),
            self.assertLogs("maestrod", level="WARNING") as logs,
        ):
            self.assertEqual(session.close(), [])
        self.assertTrue(any("could not save" in line for line in logs.output))
        self.assertTrue(session.diversion.record_pending)
        # The stale entry still exists, but the controls are free, so a new
        # run drops it without writing to the mouse.
        self.assertIsNotNone(ledger.get(device_key(device)))
        session.diversion.retry_record()
        self.assertFalse(session.diversion.record_pending)
        self.assertFalse(self.path.exists())

    def test_stale_entry_for_free_controls_is_dropped(self):
        device = FakeDevice()
        self.ledger().update(device_key(device), {GESTURE: (True, DIVERTED)}, 0x81)
        session = self.session(device)
        self.assertEqual(session.diversion.check_leftovers(), [])
        self.assertFalse(self.path.exists())
        self.assertEqual(writes(device, GESTURE), [])

    def test_write_syncs_file_and_directory(self):
        synced = []
        real = ownership._fsync_directory
        with patch.object(
            ownership, "_fsync_directory", side_effect=lambda p: synced.append(p) or real(p)
        ):
            ledger = self.ledger()
            key = device_key(FakeDevice())
            ledger.update(key, {GESTURE: (True, DIVERTED)}, None)
            ledger.update(key, {}, None)
        self.assertEqual(synced, [self.path.parent, self.path.parent])

    # --- record file safety --------------------------------------------------

    def test_symlink_and_special_files_are_refused(self):
        key = device_key(FakeDevice())
        target = self.root / "elsewhere.json"
        target.write_bytes(self.record(key))
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(target)
        ledger = self.ledger()
        with self.assertLogs("maestrod", level="WARNING"):
            self.assertEqual(ledger.load(), {})
        with self.assertRaises(RecordError):
            ledger.update(key, {GESTURE: (True, DIVERTED)}, None)
        self.assertEqual(target.read_bytes(), self.record(key))
        self.path.unlink()
        os.mkfifo(self.path)
        ledger = self.ledger()
        with self.assertLogs("maestrod", level="WARNING") as logs:
            self.assertEqual(ledger.load(), {})
        self.assertIn("not a regular file", logs.output[0])

    def test_record_owned_by_someone_else_is_refused(self):
        key = device_key(FakeDevice())
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(self.record(key))
        ledger = self.ledger()
        with (
            patch.object(ownership.os, "getuid", return_value=os.getuid() + 1),
            self.assertLogs("maestrod", level="WARNING") as logs,
        ):
            self.assertEqual(ledger.load(), {})
        self.assertIn("not owned by this user", logs.output[0])
        self.assertEqual(set(ledger.load()), {key})

    # --- other mouse apps -----------------------------------------------------

    def fake_proc(self, processes):
        proc = self.root / "proc"
        for pid, (comm, argv) in processes.items():
            entry = proc / str(pid)
            entry.mkdir(parents=True)
            (entry / "comm").write_text(comm + "\n")
            (entry / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (proc / "self").mkdir(parents=True, exist_ok=True)
        return proc

    def test_other_mouse_apps_are_found_by_argv(self):
        cases = {
            "solaar": ("python3", ["/usr/bin/python3", "/usr/bin/solaar"]),
            "input-remapper": ("input-remapper", ["/usr/bin/input-remapper-service"]),
            "juhradial": ("juhradial-mx", ["juhradial-mx"]),
            "openlogi": ("openlogi", ["/opt/openlogi/openlogi", "--tray"]),
            "logitune": ("logitune", ["logitune"]),
            "mx-options": ("python3", ["python3", "/home/u/mx-options.py"]),
            "logid": ("logid", ["/usr/bin/logid"]),
        }
        for owner, process in cases.items():
            with self.subTest(owner=owner):
                proc = self.fake_proc({100: process})
                self.assertEqual(find_other_owner(proc), ("100", owner))
                for entry in proc.iterdir():
                    for item in entry.iterdir():
                        item.unlink()
                    entry.rmdir()
        proc = self.fake_proc(
            {
                7: ("bash", ["bash", "-c", "solaar"]),  # only argv[0..1] count
                8: ("maestrod", ["python3", "-m", "maestro.daemon"]),
                9: ("logiopsx", ["logiopsx"]),
            }
        )
        self.assertIsNone(find_other_owner(proc))
        self.assertIsNone(find_other_owner(self.root / "missing"))

    def test_startup_refusal_is_unchanged_for_non_hidpp_apps(self):
        proc = self.fake_proc({5: ("input-remapper", ["input-remapper-service"])})
        self.assertIsNone(check_other_owners(proc))  # input-remapper does not pause the service
        proc = self.fake_proc({6: ("solaar", ["solaar"])})
        self.assertEqual(check_other_owners(proc), "Solaar")
        proc = self.fake_proc({7: ("logid", ["/usr/bin/logid"])})
        self.assertEqual(check_other_owners(proc), "logiops")


if __name__ == "__main__":
    unittest.main()
