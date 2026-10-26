"""Independent-review regressions for ownership, suspension, settings, and Bluetooth."""

import copy
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput, packet

from maestro import hidpp
from maestro.daemon.actions import Actions
from maestro.daemon.config import ConfigError, ConfigFile
from maestro.daemon.events import decode
from maestro.daemon.profiles import resolve
from maestro.daemon.service import Daemon, MouseSession


class OwnershipRegressions(unittest.TestCase):
    def daemon(self, directory, scans):
        daemon = Daemon(ConfigFile(Path(directory) / "config.json"), discover=lambda: next(scans))
        daemon.actions = Actions(FakeOutput())
        daemon.config.raw = {"thumb_wheel": {"mode": "tabs"}}
        self.addCleanup(daemon.close)
        return daemon

    def test_transient_scan_error_retains_owned_diversions_and_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            device = FakeDevice()
            scans = iter([[device], hidpp.ScanResult(errors=["pairing read timed out"]), [device]])
            daemon = self.daemon(directory, scans)
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
                original = daemon.sessions[0]
                self.assertEqual(device.reporting[0xC3], 0x11)
                daemon.discover_devices()
                self.assertIn(original, daemon.sessions)
                self.assertTrue(device.writable)
                self.assertFalse(original.online)
                self.assertEqual(original.diversion.owned, {0xC3: True})
                daemon.discover_devices()
                self.assertIs(daemon.sessions[0], original)
                self.assertTrue(original.online)
            daemon.close()
            self.assertEqual(device.reporting[0xC3], 0)
            self.assertEqual(device.thumb_mode[0] & 1, 0)

    def test_shutdown_after_transient_scan_error_undiverts_original_mouse(self):
        with tempfile.TemporaryDirectory() as directory:
            device = FakeDevice()
            daemon = self.daemon(directory, iter([[device], hidpp.ScanResult(errors=["timeout"])]))
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
                daemon.discover_devices()
            daemon.close()
            self.assertEqual(device.reporting[0xC3], 0)
            self.assertEqual(device.thumb_mode[0] & 1, 0)

    def test_discovery_exception_keeps_ownership_and_does_not_revoke_writability(self):
        with tempfile.TemporaryDirectory() as directory:
            device = FakeDevice()
            daemon = self.daemon(directory, iter([[device]]))
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
            original = daemon.sessions[0]
            daemon.discover = lambda: (_ for _ in ()).throw(hidpp.Timeout("receiver timeout"))
            daemon.discover_devices()
            self.assertEqual(daemon.sessions, [original])
            self.assertEqual(original.identity_state, "uncertain")
            self.assertTrue(device.writable)
            daemon.close()
            self.assertEqual(device.reporting[0xC3], 0)

    def test_confirmed_replacement_retains_cleanup_until_original_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            device, replacement = FakeDevice(), FakeDevice("M720 Triathlon")
            daemon = self.daemon(directory, iter([[device], [replacement]]))
            valid = [True]
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
                original = daemon.sessions[0]
                original.diversion.guard = lambda: valid[0]
                device.calls.clear()
                valid[0] = False
                daemon.discover_devices()
            self.assertEqual(daemon.sessions, [])
            self.assertEqual(daemon.retired_sessions, [original])
            self.assertEqual(original.identity_state, "changed")
            self.assertEqual(device.calls, [])
            self.assertEqual(replacement.calls, [])
            self.assertEqual(device.reporting[0xC3], 0x11)
            valid[0] = True
            daemon.close()
            self.assertEqual(device.reporting[0xC3], 0)
            self.assertEqual(device.thumb_mode[0] & 1, 0)
            self.assertEqual(replacement.calls, [])

    def test_returning_original_reuses_retired_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            device, replacement = FakeDevice(), FakeDevice("M720 Triathlon")
            daemon = self.daemon(directory, iter([[device], [replacement], [device]]))
            valid = [True]
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
                original = daemon.sessions[0]
                original.diversion.guard = lambda: valid[0]
                valid[0] = False
                daemon.discover_devices()
                valid[0] = True
                daemon.discover_devices()
            self.assertEqual(daemon.sessions, [original])
            self.assertEqual(daemon.retired_sessions, [])
            self.assertTrue(original.online)
            daemon.close()
            self.assertEqual(device.reporting[0xC3], 0)

    def test_failed_stream_does_not_forget_owned_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            device = FakeDevice()
            daemon = self.daemon(directory, iter([[device]]))
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
            device.channel.read_events = lambda: (_ for _ in ()).throw(OSError("stream failure"))
            with self.assertLogs("maestrod", level="WARNING"):
                daemon.process_events()
            self.assertEqual(daemon.sessions[0].diversion.owned, {0xC3: True})
            self.assertFalse(daemon.sessions[0].online)
            daemon.close()
            self.assertEqual(device.reporting[0xC3], 0)

    def test_verified_new_reader_preserves_original_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            original_device, fresh_reader = FakeDevice(), FakeDevice()
            fresh_reader.reporting = original_device.reporting
            fresh_reader.thumb_mode = original_device.thumb_mode
            daemon = self.daemon(directory, iter([[original_device], [fresh_reader]]))
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
                session = daemon.sessions[0]
                original_device.channel.read_events = lambda: (_ for _ in ()).throw(OSError("EOF"))
                with self.assertLogs("maestrod", level="WARNING"):
                    daemon.process_events()
                daemon.discover_devices()
            self.assertIs(daemon.sessions[0], session)
            self.assertIs(session.device, fresh_reader)
            self.assertTrue(session.verified)
            self.assertEqual(session.diversion.owned, {0xC3: True})
            self.assertEqual(daemon.failed_channels, set())
            daemon.close()
            self.assertEqual(original_device.reporting[0xC3], 0)
            self.assertEqual(original_device.thumb_mode[0] & 1, 0)

    def test_read_only_session_adopts_fresh_writable_device_and_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            read_only, writable = FakeDevice(writable=False), FakeDevice()
            daemon = self.daemon(directory, iter([[read_only], [writable]]))
            daemon.config.raw["settings"] = {"dpi": 1200}
            old_guard, fresh_guard = lambda: False, lambda: True
            with (
                patch("maestro.daemon.service.adopt_channels"),
                patch.object(daemon, "_guard", side_effect=[old_guard, fresh_guard]),
            ):
                daemon.discover_devices()
                session = daemon.sessions[0]
                ownership = session.diversion.owned
                self.assertFalse(session.online)
                self.assertFalse(ownership)
                read_only.calls.clear()
                daemon.discover_devices()
            self.assertEqual(daemon.sessions, [session])
            self.assertIs(session.device, writable)
            self.assertIs(session.diversion.device, writable)
            self.assertIs(session.diversion.guard, fresh_guard)
            self.assertIs(session.diversion.owned, ownership)
            self.assertTrue(session.online)
            self.assertTrue(session.verified)
            self.assertEqual(writable.dpi, 1200)
            self.assertEqual(writable.reporting[0xC3], 0x11)
            self.assertEqual(read_only.calls, [])
            daemon.close()
            self.assertEqual(writable.reporting[0xC3], 0)
            self.assertEqual(writable.thumb_mode[0] & 1, 0)

    def test_cleanup_uses_saved_original_identity_after_metadata_is_revoked(self):
        with tempfile.TemporaryDirectory() as directory:
            original, replacement, returning = (
                FakeDevice(),
                FakeDevice("M720 Triathlon"),
                FakeDevice(),
            )
            returning.reporting = original.reporting
            returning.thumb_mode = original.thumb_mode
            daemon = self.daemon(directory, iter([[original], [replacement], [returning]]))
            with patch("maestro.daemon.service.adopt_channels"):
                daemon.discover_devices()
                session = daemon.sessions[0]
                original.kind, original.model = "keyboard", None
                original.calls.clear()
                daemon.discover_devices()
                daemon.discover_devices()
            self.assertIs(daemon.sessions[0], session)
            self.assertIs(session.device, returning)
            self.assertEqual(original.calls, [])
            daemon.close()
            self.assertEqual(original.reporting[0xC3], 0)
            self.assertEqual(original.calls, [])

    def test_shutdown_retries_a_transient_identity_read(self):
        device = FakeDevice()
        session = MouseSession(device, Actions(FakeOutput()))
        session.configure(resolve({"thumb_wheel": {"mode": "tabs"}}, session.identity))
        checks = iter([hidpp.Timeout("temporary pairing read failure")])

        def guard():
            failure = next(checks, None)
            if failure is not None:
                raise failure
            return True

        session.diversion.guard = guard
        self.assertEqual(session.close(), [])
        self.assertEqual(device.reporting[0xC3], 0)
        self.assertEqual(device.thumb_mode[0] & 1, 0)

    def test_failed_reconnect_releases_input_and_blocks_every_action_until_configured(self):
        device, output = FakeDevice(), FakeOutput()
        valid = [True]
        session = MouseSession(device, Actions(output), endpoint_guard=lambda: valid[0])
        self.addCleanup(session.close)
        options = resolve(
            {
                "buttons": {"gesture": {"type": "key", "keys": ["CTRL"]}},
                "thumb_wheel": {"mode": "volume"},
            },
            session.identity,
        )
        session.configure(options)
        session.event(("buttons", {0xC3}))
        self.assertIn(29, output.held)
        valid[0] = False
        session.event(("reconnect", None))
        self.assertFalse(output.held)
        self.assertFalse(session.online)
        count = len(output.events)
        for event in (
            ("buttons", {0xC3}),
            ("move", (100, 0)),
            ("thumb", (120, False)),
            ("buttons", set()),
        ):
            session.event(event)
        self.assertEqual(len(output.events), count)
        self.assertFalse(output.held)
        valid[0] = True
        session.event(("buttons", {0xC3}))
        self.assertFalse(output.held)
        session.configure(options, force=True)
        session.event(("buttons", {0xC3}))
        self.assertIn(29, output.held)
        session.close()
        self.assertFalse(output.held)

    def test_pairing_read_errors_suspend_and_release_held_input(self):
        for failure in (hidpp.Timeout("timeout"), hidpp.HidppError("pairing read error")):
            with self.subTest(failure=failure):
                device, output = FakeDevice(), FakeOutput()
                session = MouseSession(device, Actions(output))
                options = resolve(
                    {"buttons": {"gesture": {"type": "key", "keys": ["CTRL"]}}}, session.identity
                )
                session.configure(options)
                session.event(("buttons", {0xC3}))
                with patch.object(session.diversion, "guard", side_effect=failure):
                    session.reconcile(options)
                    self.assertFalse(output.held)
                    self.assertFalse(session.verified)
                    self.assertEqual(session.identity_state, "uncertain")
                    count = len(output.events)
                    session.event(("buttons", {0xC3}))
                    self.assertEqual(len(output.events), count)
                session.close()
                self.assertEqual(device.reporting[0xC3], 0)


class SettingsRegressions(unittest.TestCase):
    def daemon(self, directory):
        path = Path(directory) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "devices": [
                        {
                            "name": "Saved mouse",
                            "match": {"name": "MX Master 2S", "index": 1},
                            "settings": {"dpi": 1000},
                        },
                        {
                            "name": "Late workspace rule",
                            "match": {"path": "/dev/fake"},
                            "settings": {"dpi": 1600},
                        },
                    ]
                }
            )
        )
        daemon = Daemon(ConfigFile(path))
        daemon.actions = Actions(FakeOutput())
        device = FakeDevice()
        session = MouseSession(device, daemon.actions)
        daemon.sessions.append(session)
        session.configure(daemon.options(session))
        self.addCleanup(daemon.close)
        return daemon, device, session

    def test_unsupported_reload_setting_reports_error_and_keeps_actions_and_ipc_active(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon, device, session = self.daemon(directory)
            raw = {
                "settings": {"dpi": 1234, "invert": True},
                "buttons": {"back": {"type": "key", "keys": ["CTRL"]}},
                "gesture": {"tap": {"type": "key", "keys": ["SUPER"]}},
            }
            # Start with the same working actions before introducing an unsupported DPI.
            working = copy.deepcopy(raw)
            working["settings"]["dpi"] = 1200
            working["settings"]["invert"] = False
            daemon.config.replace(working)
            session.configure(daemon.options(session))
            daemon.config.path.write_text(json.dumps(raw))
            with self.assertLogs("maestrod", level="ERROR") as logs:
                self.assertFalse(daemon.refresh_config())
                with self.assertRaisesRegex(ConfigError, "dpi:.*1234"):
                    daemon.handle({"op": "reload"})
                session.reconcile(daemon.options(session))
            self.assertIn("1234", " ".join(logs.output))
            self.assertTrue(any("1234" in error for error in session.errors))
            self.assertTrue(session.online)
            self.assertTrue(session.verified)
            self.assertEqual(device.dpi, 1200)
            self.assertEqual(device.wheel_flags & 4, 4)
            self.assertEqual(device.reporting[0x53], 1)
            self.assertEqual(device.reporting[0xC3], 0x11)
            session.event(("buttons", {0x53}))
            self.assertIn(29, daemon.actions.output.held)
            session.event(("buttons", set()))
            session.event(("buttons", {0xC3}))
            session.event(("buttons", set()))
            self.assertIn(("press", 125), daemon.actions.output.events)
            self.assertFalse(daemon.actions.output.held)
            response = daemon.handle({"op": "set", "settings": {"dpi": 1600}})
            self.assertTrue(response["ok"])
            self.assertEqual(response["status"]["dpi"]["current"], 1600)
            self.assertEqual(session.errors, [])
            self.assertTrue(daemon.refresh_config())
            daemon.close()
            self.assertEqual(device.reporting[0x53], 0)
            self.assertEqual(device.reporting[0xC3], 0)

    def test_ipc_saved_setting_wins_later_matching_rules_and_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon, device, session = self.daemon(directory)
            self.assertEqual(device.dpi, 1600)
            response = daemon.handle({"op": "set", "settings": {"dpi": 1200}})
            self.assertTrue(response["ok"])
            self.assertEqual(response["status"]["dpi"]["current"], 1200)
            self.assertEqual(device.dpi, 1200)
            saved = ConfigFile(daemon.config.path)
            self.assertEqual(resolve(saved.raw, session.identity)["settings"]["dpi"], 1200)

    def test_final_override_preserves_unrequested_settings_and_button_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon, device, session = self.daemon(directory)
            raw = daemon.config.raw
            raw["devices"][0]["settings"].update(invert=False, smartshift={"threshold": 10})
            raw["devices"][0]["buttons"] = {"back": {"type": "none"}}
            raw["devices"][1]["settings"].update(invert=True, smartshift={"threshold": 20})
            raw["devices"][1]["buttons"] = {"back": None}
            daemon.config.replace(raw)
            session.configure(daemon.options(session))
            response = daemon.handle({"op": "set", "settings": {"dpi": 1200}})
            self.assertTrue(response["ok"])
            self.assertEqual(device.dpi, 1200)
            self.assertTrue(device.wheel_flags & 4)
            self.assertEqual(device.smartshift[1], 20)
            self.assertIsNone(daemon.options(session)["buttons"]["back"])

    def test_nested_smartshift_and_scroll_values_win_and_are_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon, device, session = self.daemon(directory)
            requested = {"smartshift": {"mode": "freespin", "threshold": 30}, "invert": True}
            response = daemon.handle({"op": "set", "settings": requested})
            self.assertTrue(response["ok"])
            self.assertEqual(response["status"]["smartshift"]["threshold"], 30)
            self.assertEqual(device.smartshift, [1, 30])
            self.assertEqual(device.wheel_flags & 4, 4)
            self.assertEqual(
                daemon.options(session)["settings"]["smartshift"], requested["smartshift"]
            )

    def test_overridden_request_errors_with_rule_name_and_restores_original_value(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon, device, _ = self.daemon(directory)
            before = copy.deepcopy(daemon.config.raw)
            with patch.object(daemon.config, "save_device_settings"):
                with self.assertRaisesRegex(ValueError, "Late workspace rule"):
                    daemon.handle({"op": "set", "settings": {"dpi": 1200}})
            self.assertEqual(device.dpi, 1600)
            self.assertEqual(daemon.config.raw, before)

    def test_incorrect_final_hardware_readback_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon, device, session = self.daemon(directory)
            original = copy.deepcopy(daemon.config.raw)

            def wrong_readback(options):
                device.dpi = 1600

            with patch.object(session, "configure", side_effect=wrong_readback):
                with self.assertRaisesRegex(ValueError, "readback"):
                    daemon.handle({"op": "set", "settings": {"dpi": 1200}})
            self.assertEqual(device.dpi, 1600)
            self.assertEqual(daemon.config.raw, original)
            self.assertEqual(ConfigFile(daemon.config.path).raw, original)


class BluetoothRegressions(unittest.TestCase):
    def test_zero_address_alias_is_accepted_only_for_verified_bluetooth(self):
        device = FakeDevice()
        device.index = hidpp.DIRECT_INDEX
        device.node = hidpp.HidrawNode("/dev/bt", 5, 0x46D, 0xB019, "MX Master 2S")
        report = packet(2, 0, struct.pack("!4H", 0xC3, 0, 0, 0), index=0)
        self.assertEqual(decode(report, device, device.features), ("buttons", {0xC3}))
        device.writable = False
        self.assertIsNone(decode(report, device, device.features))
        device.writable = True
        device.kind = "keyboard"
        self.assertIsNone(decode(report, device, device.features))
        device.kind = "mouse"
        device.model = None
        self.assertIsNone(decode(report, device, device.features))
        device.model = "MX Master 2S"
        device.node = hidpp.HidrawNode("/dev/receiver", 3, 0x46D, 0xC52B, "receiver")
        device.index = 1
        self.assertIsNone(decode(report, device, device.features))
        exact = packet(2, 0, struct.pack("!4H", 0xC3, 0, 0, 0), index=1)
        self.assertEqual(decode(exact, device, device.features), ("buttons", {0xC3}))
