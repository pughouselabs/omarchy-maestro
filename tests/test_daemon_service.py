import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput

from maestro import hidpp
from maestro.daemon.actions import Actions
from maestro.daemon.config import ConfigFile
from maestro.daemon.profiles import resolve
from maestro.daemon.service import Daemon, MouseSession, apply_settings, check_other_owners


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeDevice()
        self.output = FakeOutput()
        self.session = MouseSession(
            self.device,
            Actions(
                self.output,
                desktop="hyprland",
                desktop_handler=lambda action: self.output.events.append(("desktop", action)),
            ),
        )
        self.addCleanup(self.session.close)

    def test_default_gesture_events_and_undivert_on_exit(self):
        self.session.configure(resolve({}, self.session.identity))
        self.session.event(("buttons", {0xC3}))
        self.session.event(("move", (60, 0)))
        self.session.event(("buttons", set()))
        self.assertEqual(self.output.events, [("desktop", "workspace_next")])
        self.session.close()
        self.assertEqual(self.device.reporting[0xC3], 0)
        self.assertFalse(self.device.thumb_mode[0] & 1)

    def test_remapped_middle_can_be_held_across_profile_change(self):
        raw = {
            "gesture": {"enabled": False},
            "buttons": {"middle": {"type": "mouse", "button": "middle"}},
        }
        self.session.configure(resolve(raw, self.session.identity))
        self.session.event(("buttons", {0x52}))
        self.assertIn(274, self.output.held)
        self.session.configure(resolve({"gesture": {"enabled": False}}, self.session.identity))
        self.assertIn(0x52, self.session.diversion.owned)
        self.session.event(("buttons", set()))
        self.assertFalse(self.output.held)
        self.assertNotIn(0x52, self.session.diversion.owned)

    def test_explicit_gesture_button_mapping_overrides_default_gestures(self):
        raw = {"buttons": {"gesture": {"type": "key", "keys": ["CTRL", "C"]}}}
        self.session.configure(resolve(raw, self.session.identity))
        self.assertIsNone(self.session.gesture_cid)
        self.session.event(("buttons", {0xC3}))
        self.session.event(("disconnected", None))
        self.assertFalse(self.output.held)
        self.assertFalse(self.session.online)

    def test_native_null_stops_gestures_and_absent_mapping_restores_them(self):
        for buttons, expected in (
            ({}, [("desktop", "workspace_next")]),
            ({"gesture": None}, []),
            ({}, [("desktop", "workspace_next")]),
        ):
            with self.subTest(buttons=buttons):
                self.output.events.clear()
                self.session.configure(resolve({"buttons": buttons}, self.session.identity))
                native = "gesture" in buttons
                self.assertEqual(self.session.gesture_cid is None, native)
                self.assertEqual(0xC3 not in self.session.diversion.owned, native)
                self.assertEqual(self.device.reporting[0xC3], 0 if native else 0x11)
                self.session.event(("buttons", {0xC3}))
                self.session.event(("move", (60, 0)))
                self.session.event(("buttons", set()))
                self.assertEqual(self.output.events, expected)

    def test_native_wheel_is_never_diverted_by_default(self):
        self.session.configure(resolve({}, self.session.identity))
        self.assertFalse(any(f == hidpp.THUMB_WHEEL and fn == 2 for f, fn, _ in self.device.calls))

    def test_2s_without_thumb_feature_keeps_native_scroll(self):
        self.device.features.pop(hidpp.THUMB_WHEEL)
        self.session.indexes[hidpp.THUMB_WHEEL] = None
        self.session.configure(resolve({"thumb_wheel": {"mode": "tabs"}}, self.session.identity))
        self.assertFalse(self.session.diversion.thumb_owned)
        self.assertTrue(any("0x2150" in error for error in self.session.errors))
        self.assertEqual(self.device.reporting[0xC3], 0x11)

    def test_wheel_accumulation_and_return_to_native_on_profile_exit(self):
        raw = {"thumb_wheel": {"mode": "tabs", "step": 100}}
        self.session.configure(resolve(raw, self.session.identity))
        self.session.event(("thumb", (40, True)))
        self.session.event(("thumb", (61, False)))
        self.assertEqual(
            self.output.events,
            [("press", 29), ("press", 109), ("release", 109), ("release", 29)],
        )
        self.session.configure(resolve({}, self.session.identity))
        self.assertEqual(self.device.thumb_mode, [0, 1])

    def test_wake_restores_settings_and_diversion_after_power_loss(self):
        raw = {
            "settings": {"dpi": 1200, "smartshift": {"threshold": 20}, "invert": True},
            "thumb_wheel": {"mode": "volume"},
        }
        self.session.configure(resolve(raw, self.session.identity))
        self.device.dpi, self.device.smartshift, self.device.wheel_flags = 800, [1, 10], 2
        self.device.reporting[0xC3] = 0
        self.device.thumb_mode[0] = 0
        self.session.event(("reconnect", None))
        self.assertEqual(self.device.dpi, 1200)
        self.assertEqual(self.device.smartshift, [1, 20])
        self.assertEqual(self.device.wheel_flags, 6)
        self.assertEqual(self.device.reporting[0xC3], 0x11)
        self.assertEqual(self.device.thumb_mode, [1, 1])

    def test_settings_skip_equal_values_and_report_wrong_readback(self):
        self.assertEqual(apply_settings(self.device, {"dpi": 1000}), [])
        self.assertFalse(
            any(f == hidpp.ADJUSTABLE_DPI and fn == 3 for f, fn, _ in self.device.calls)
        )
        with patch("maestro.daemon.service.mouse.set_dpi", return_value=999):
            self.assertIn("readback", apply_settings(self.device, {"dpi": 1200})[0])

    def test_sleep_during_configuration_retries_on_wireless_wake(self):
        options = resolve({}, self.session.identity)
        self.device.fail_enable = True
        self.session.configure(options)
        self.assertFalse(self.session.online)
        self.assertEqual(self.session.diversion.owned, {0xC3: True})
        self.session.event(("reconnect", None))
        self.assertTrue(self.session.online)
        self.assertIsNone(self.session.pending)
        self.assertEqual(self.device.reporting[0xC3], 0x11)

    def test_reload_removes_all_diversions(self):
        self.session.configure(
            resolve(
                {"thumb_wheel": {"mode": "tabs"}, "buttons": {"back": {"type": "none"}}},
                self.session.identity,
            )
        )
        self.session.configure(resolve({"gesture": {"enabled": False}}, self.session.identity))
        self.assertFalse(self.session.diversion.owned)
        self.assertFalse(self.session.diversion.thumb_owned)
        self.assertEqual(set(self.device.reporting.values()), {0})


class LifecycleTests(unittest.TestCase):
    def test_sighup_reload_and_both_stop_signals_cleanup(self):
        for stop_signal in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=stop_signal), tempfile.TemporaryDirectory() as directory:
                config = ConfigFile(Path(directory) / "config.json")
                device = FakeDevice()
                device.channel.read_events = lambda: []
                output = FakeOutput()
                windows = SimpleNamespace(
                    connect=lambda: None,
                    poll=lambda: {},
                    dirty=lambda: False,
                    close=lambda: None,
                    error=None,
                    socket=None,
                )
                handlers, calls = {}, []

                def install(signum, callback, handlers=handlers):
                    previous = handlers.get(signum, signal.SIG_DFL)
                    handlers[signum] = callback
                    return previous

                def poll(now, calls=calls, handlers=handlers, stop_signal=stop_signal):
                    calls.append(now)
                    target = signal.SIGHUP if len(calls) == 1 else stop_signal
                    handlers[target](target, None)

                server = SimpleNamespace(
                    poll=poll, listener=SimpleNamespace(fileno=lambda: 123), close=lambda: None
                )
                daemon = Daemon(
                    config,
                    output_factory=lambda output=output: output,
                    discover=lambda device=device: [device],
                    windows=windows,
                    server_factory=lambda handler, server=server: server,
                )
                with (
                    patch("maestro.daemon.service.adopt_channels"),
                    patch("maestro.daemon.service.check_other_owners"),
                    patch("maestro.daemon.service.signal.signal", side_effect=install),
                    patch("maestro.daemon.service.select.select", return_value=([], [], [])),
                    patch.object(config, "reload", wraps=config.reload) as reload,
                ):
                    daemon.run()
                self.assertEqual(reload.call_count, 1)
                self.assertTrue(output.closed)
                self.assertEqual(set(device.reporting.values()), {0})
                self.assertEqual(handlers[stop_signal], signal.SIG_DFL)

    def test_crash_finally_releases_keys_and_all_diversions(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            config.raw = {
                "thumb_wheel": {"mode": "tabs"},
                "buttons": {"middle": {"type": "key", "keys": ["CTRL"]}},
            }
            device = FakeDevice()
            output = FakeOutput()
            windows = SimpleNamespace(
                connect=lambda: None, poll=lambda: {}, close=lambda: None, error=None
            )
            server = SimpleNamespace(close=lambda: None)
            daemon = Daemon(
                config,
                output_factory=lambda: output,
                discover=lambda: [device],
                windows=windows,
                server_factory=lambda handler: server,
            )

            def crash():
                daemon.sessions[0].event(("buttons", {0x52}))
                raise RuntimeError("simulated crash")

            with (
                patch("maestro.daemon.service.adopt_channels"),
                patch("maestro.daemon.service.check_other_owners"),
                patch("maestro.daemon.service.hidpp.find_hidpp_nodes", return_value=[]),
                patch.object(daemon, "process_events", side_effect=crash),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    daemon.run()
            self.assertTrue(output.closed)
            self.assertFalse(output.held)
            self.assertEqual(set(device.reporting.values()), {0})
            self.assertEqual(device.thumb_mode, [0, 1])
            daemon.close()

    def test_no_input_access_prevents_mouse_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon(
                ConfigFile(Path(directory) / "config.json"),
                output_factory=lambda: (_ for _ in ()).throw(PermissionError("no uinput")),
                server_factory=lambda handler: SimpleNamespace(close=lambda: None),
            )
            with (
                patch("maestro.daemon.service.check_other_owners"),
                patch.object(daemon, "discover_devices") as discover,
            ):
                with self.assertRaises(PermissionError):
                    daemon.run()
                discover.assert_not_called()

    def test_other_owner_guard_uses_process_name_not_arbitrary_args(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            pid = proc / "123"
            pid.mkdir()
            (pid / "comm").write_text("bash\n")
            (pid / "cmdline").write_bytes(b"bash\0-c\0echo solaar\0")
            check_other_owners(proc)
            (pid / "comm").write_text("solaar\n")
            with self.assertRaisesRegex(RuntimeError, "PID 123"):
                check_other_owners(proc)

    def test_ipc_set_is_saved_and_failed_save_rolls_back_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            device = FakeDevice()
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            self.addCleanup(daemon.close)
            session.configure(resolve({}, session.identity))
            self.assertTrue(daemon.handle({"op": "set", "settings": {"dpi": 1200}})["ok"])
            self.assertEqual(device.dpi, 1200)
            self.assertEqual(resolve(config.raw, session.identity)["settings"]["dpi"], 1200)
            with patch.object(config, "save_device_settings", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    daemon.handle({"op": "set", "settings": {"dpi": 1600}})
            self.assertEqual(device.dpi, 1200)
            for message in (
                {"op": "set", "device": True, "settings": {"dpi": 1200}},
                {"op": "set", "settings": {"dpi": 1234}},
                {"op": "unknown"},
            ):
                with self.assertRaises(ValueError):
                    daemon.handle(message)

    def test_invalid_reload_keeps_live_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"settings":{"dpi":1200}}')
            daemon = Daemon(ConfigFile(path))
            daemon.actions = Actions(FakeOutput())
            path.write_text("{")
            with self.assertLogs("maestrod", level="ERROR"):
                self.assertFalse(daemon.refresh_config())
            self.assertEqual(daemon.config.raw["settings"]["dpi"], 1200)
