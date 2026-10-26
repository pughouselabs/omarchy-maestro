"""Daemon discovery must inherit every core identity/write restriction."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput
from test_core_discovery import DiscoveryChannel

from maestro import hidpp
from maestro.daemon.actions import Actions
from maestro.daemon.config import ConfigFile
from maestro.daemon.service import Daemon, MouseSession, apply_settings


class DaemonDiscoveryTests(unittest.TestCase):
    def daemon(self, directory):
        daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
        daemon.actions = Actions(FakeOutput())
        self.addCleanup(daemon.close)
        return daemon

    def test_renamed_bluetooth_keyboard_never_opens_channel_or_session(self):
        for name in ("MX Master 3S", "Logitech Mouse Keyboard Combo"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                daemon = self.daemon(directory)
                node = hidpp.HidrawNode("/dev/keys", 5, 0x46D, 0xB360, name)
                with (
                    patch.object(hidpp, "find_hidpp_nodes", return_value=[node]),
                    patch.object(hidpp, "Channel") as channel,
                ):
                    daemon.discover_devices()
                channel.assert_not_called()
                self.assertEqual(daemon.sessions, [])
                self.assertEqual(daemon.devices, [])

    def test_m720_with_mx_system_name_is_status_only(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = self.daemon(directory)
            node = hidpp.HidrawNode("/dev/m720", 5, 0x46D, 0xB999, "MX Master 3S")
            channel = DiscoveryChannel(node.path, names={0xFF: "M720 Triathlon"})
            with (
                patch.object(hidpp, "find_hidpp_nodes", return_value=[node]),
                patch.object(hidpp, "Channel", return_value=channel),
                patch("maestro.daemon.service.adopt_channels"),
            ):
                daemon.discover_devices()
            self.assertEqual(daemon.sessions, [])
            self.assertIsNone(daemon.devices[0].model)
            request_count = len(channel.requests)
            with self.assertRaisesRegex(ValueError, "unsupported"):
                daemon.handle({"op": "set", "settings": {"dpi": 1200}})
            self.assertEqual(len(channel.requests), request_count)
            self.assertFalse(daemon.handle({"op": "status"})["devices"][0]["supported"])
            self.assertTrue(
                all(
                    feature == 0 or feature == 3 and function in (0, 1, 2)
                    for _, feature, function, _ in channel.requests
                )
            )

    def test_unverified_bluetooth_fallback_cannot_configure_or_divert(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = self.daemon(directory)
            daemon.config.raw = {"settings": {"dpi": 1200, "invert": True}}
            node = hidpp.HidrawNode("/dev/mx", 5, 0x46D, 0xB999, "MX Master 3S")
            channel = DiscoveryChannel(node.path, name_error=True)
            with (
                patch.object(hidpp, "find_hidpp_nodes", return_value=[node]),
                patch.object(hidpp, "Channel", return_value=channel),
                patch("maestro.daemon.service.adopt_channels"),
            ):
                daemon.discover_devices()
                self.assertEqual(len(daemon.sessions), 1)
                self.assertFalse(daemon.sessions[0].device.writable)
                self.assertFalse(daemon.sessions[0].diversion.owned)
                self.assertEqual(daemon.handle({"op": "status"})["devices"][0]["writable"], False)
                before = len(channel.requests)
                with self.assertRaisesRegex(ValueError, "writes are disabled"):
                    daemon.handle({"op": "set", "settings": {"dpi": 1200}})
                self.assertEqual(len(channel.requests), before)
            self.assertTrue(
                all(
                    feature == 0 or feature == 3 and function in (0, 1, 2)
                    for _, feature, function, _ in channel.requests
                )
            )

    def test_read_only_supported_mouse_has_zero_settings_or_diversion_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = self.daemon(directory)
            device = FakeDevice(writable=False)
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            device.calls.clear()
            session.configure({"settings": {"dpi": 1200, "invert": True}})
            self.assertTrue(apply_settings(device, {"dpi": 1200}))
            self.assertEqual(device.calls, [])
            with self.assertRaisesRegex(ValueError, "writes are disabled"):
                daemon.handle({"op": "set", "settings": {"invert": True}})
            self.assertEqual(device.calls, [])
            self.assertFalse(session.diversion.owned)
