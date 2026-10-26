"""Receiver, Bluetooth, and privacy checks using fake HID++ transports."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro import __main__ as cli
from maestro import devices, hidpp, mouse


class PairingWire(hidpp.Channel):
    def __init__(self, reply):
        self.path = "fake receiver"
        self.fd = 42
        self.reply = reply
        self.sent = []

    def _drain(self):
        pass

    def _read(self, deadline):
        return self.reply


class PairingParserTests(unittest.TestCase):
    def _read(self, reply, slot, connection):
        wire = PairingWire(reply)
        with patch.object(
            hidpp.os, "write", side_effect=lambda fd, msg: wire.sent.append(msg) or len(msg)
        ):
            result = wire.pairing_info(slot, connection)
        self.assertEqual(wire.sent[0][0], hidpp.SHORT_REPORT)
        self.assertEqual(wire.sent[0][1], 0xFF)
        self.assertEqual(wire.sent[0][2:4], b"\x83\xb5")
        return result, wire.sent[0]

    def test_unifying_kind_and_wpid(self):
        reply = bytearray(20)
        reply[:5] = b"\x11\xff\x83\xb5\x20"
        reply[7:9] = b"\x40\x69"
        reply[11] = 2
        pair, request = self._read(bytes(reply), 1, "unifying")
        self.assertEqual(request[4], 0x20)
        self.assertEqual(pair, hidpp.PairingInfo(1, "mouse", 0x4069))

    def test_bolt_layout(self):
        reply = bytearray(20)
        reply[:5] = b"\x11\xff\x83\xb5\x51"
        reply[5] = 2
        reply[6:8] = b"\x9f\x40"
        pair, request = self._read(bytes(reply), 1, "bolt")
        self.assertEqual(request[4], 0x51)
        self.assertEqual(pair, hidpp.PairingInfo(1, "mouse", 0x409F))

    def test_empty_slot(self):
        pair, _ = self._read(b"\x10\xff\x8f\x83\xb5\x03\x00", 3, "unifying")
        self.assertIsNone(pair)


class DiscoveryChannel:
    def __init__(
        self, path, pairings=None, names=None, *, sleepy=False, direct_type=3, name_error=False
    ):
        self.path = path
        self.pairings = pairings or {}
        self.names = names or {0xFF: "MX Anywhere 3S"}
        self.sleepy = sleepy
        self.direct_type = direct_type
        self.name_error = name_error
        self.requests = []
        self.pairing_calls = []
        self.closed = False

    def pairing_info(self, slot, connection):
        self.pairing_calls.append((slot, connection))
        return self.pairings.get(slot)

    def request(self, index, feature_index, function, params=b"", timeout=1):
        self.requests.append((index, feature_index, function, params))
        if self.sleepy:
            raise hidpp.Timeout("sleeping")
        if feature_index == 0 and function == 1:
            return bytes((4, 5))
        if feature_index == 0 and function == 0:
            self._requested_feature = int.from_bytes(params, "big")
            return b"\x03" if self._requested_feature == hidpp.DEVICE_NAME else b"\x00"
        if feature_index == 3 and function == 2:
            return bytes((self.direct_type,))
        if feature_index == 3 and function == 0:
            if self.name_error:
                raise hidpp.HidppError("name read failed")
            return bytes((len(self.names[index]),))
        if feature_index == 3 and function == 1:
            return self.names[index].encode()[params[0] :]
        raise AssertionError((index, feature_index, function, params))

    def close(self):
        self.closed = True


class ScanTests(unittest.TestCase):
    def test_unifying_and_bolt_skip_keyboards_before_ping(self):
        unifying = hidpp.HidrawNode("/dev/u", 3, 0x046D, 0xC52B, "Logitech USB Receiver")
        bolt = hidpp.HidrawNode("/dev/b", 3, 0x046D, 0xC548, "Logi Bolt Receiver")
        channels = {
            "/dev/u": DiscoveryChannel(
                "/dev/u",
                {
                    1: hidpp.PairingInfo(1, "mouse", 0x4069),
                    2: hidpp.PairingInfo(2, "keyboard", 0x408A),
                },
                {1: "Wireless Mouse MX Master 2S"},
            ),
            "/dev/b": DiscoveryChannel(
                "/dev/b",
                {
                    1: hidpp.PairingInfo(1, "keyboard", 0x40AA),
                    2: hidpp.PairingInfo(2, "mouse", 0x409F),
                },
                {2: "MX Master 3S"},
            ),
        }
        with patch.object(hidpp, "Channel", side_effect=lambda path: channels[path]):
            scan = hidpp.scan_devices([unifying, bolt])
        self.assertEqual([d.model for d in scan.devices], ["MX Master 2S", "MX Master 3S"])
        self.assertEqual([d.index for d in scan.devices], [1, 2])
        self.assertEqual({r[0] for r in channels["/dev/u"].requests}, {1})
        self.assertEqual({r[0] for r in channels["/dev/b"].requests}, {2})
        self.assertEqual(len(channels["/dev/u"].pairing_calls), 6)
        self.assertEqual(len(channels["/dev/b"].pairing_calls), 6)
        hidpp.close_devices(scan.devices)
        self.assertTrue(all(c.closed for c in channels.values()))

    def test_bluetooth_type_gate_and_unknown_mouse(self):
        nodes = [
            hidpp.HidrawNode("/dev/keys", 5, 0x046D, 0xB360, "Logitech Mouse Keyboard Combo"),
            hidpp.HidrawNode("/dev/mx", 5, 0x046D, 0xB025, "MX Anywhere 3S"),
            hidpp.HidrawNode("/dev/other", 5, 0x046D, 0xB999, "Logitech Mouse M720"),
            hidpp.HidrawNode("/dev/not-mouse", 5, 0x046D, 0xB023, "MX Master 3"),
        ]
        channels = {
            "/dev/keys": DiscoveryChannel("/dev/keys"),
            "/dev/mx": DiscoveryChannel("/dev/mx", names={0xFF: "MX Anywhere 3S"}),
            "/dev/other": DiscoveryChannel("/dev/other", names={0xFF: "M720 Triathlon"}),
            "/dev/not-mouse": DiscoveryChannel("/dev/not-mouse", direct_type=0),
        }
        with patch.object(hidpp, "Channel", side_effect=lambda path: channels[path]):
            scan = hidpp.scan_devices(nodes)
        self.assertEqual([d.model for d in scan.devices], ["MX Anywhere 3S"])
        self.assertEqual([d.index for d in scan.devices], [0xFF])
        self.assertEqual(channels["/dev/keys"].requests, [])
        self.assertEqual(channels["/dev/other"].requests, [])
        self.assertTrue(channels["/dev/not-mouse"].closed)
        hidpp.close_devices(scan.devices)

    def test_bluetooth_hidpp_name_overrides_unverified_system_name(self):
        node = hidpp.HidrawNode("/dev/bt", 5, 0x046D, 0xB999, "MX Master 3S")
        channel = DiscoveryChannel(node.path, names={0xFF: "M720 Triathlon"})
        with patch.object(hidpp, "Channel", return_value=channel):
            scan = hidpp.scan_devices([node])
        self.assertEqual(len(scan.devices), 1)
        self.assertEqual(scan.devices[0].reported_name, "M720 Triathlon")
        self.assertIsNone(scan.devices[0].model)
        hidpp.close_devices(scan.devices)

        channel = DiscoveryChannel(node.path, names={0xFF: "M720 Triathlon"})
        stderr = io.StringIO()
        with (
            patch.object(hidpp, "find_hidpp_nodes", return_value=[node]),
            patch.object(hidpp, "Channel", return_value=channel),
            patch.object(mouse, "set_wheel") as setter,
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(cli.main(["scroll", "--invert", "on", "--device", "M720"]), 2)
        self.assertIn("unsupported Logitech device", stderr.getvalue())
        setter.assert_not_called()
        self.assertTrue(channel.closed)

    def test_unverified_system_name_fallback_is_read_only(self):
        node = hidpp.HidrawNode("/dev/bt", 5, 0x046D, 0xB999, "MX Master 3S")
        channel = DiscoveryChannel(node.path, name_error=True)
        with patch.object(hidpp, "Channel", return_value=channel):
            scan = hidpp.scan_devices([node])
        self.assertEqual(len(scan.devices), 1)
        self.assertEqual(scan.devices[0].model, "MX Master 3S")
        self.assertFalse(scan.devices[0].writable)
        hidpp.close_devices(scan.devices)

        channel = DiscoveryChannel(node.path, name_error=True)
        stderr = io.StringIO()
        with (
            patch.object(hidpp, "find_hidpp_nodes", return_value=[node]),
            patch.object(hidpp, "Channel", return_value=channel),
            patch.object(mouse, "set_wheel") as setter,
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(cli.main(["scroll", "--invert", "on", "--device", "MX Master 3S"]), 2)
        self.assertIn("identity could not be verified", stderr.getvalue())
        setter.assert_not_called()
        self.assertTrue(channel.closed)

    def test_verified_bluetooth_product_takes_precedence_over_name(self):
        node = hidpp.HidrawNode("/dev/bt", 5, 0x046D, 0xB019, "MX Master 2S")
        channel = DiscoveryChannel(node.path, names={0xFF: "M720 Triathlon"})
        with patch.object(hidpp, "Channel", return_value=channel):
            scan = hidpp.scan_devices([node])
        self.assertEqual(len(scan.devices), 1)
        self.assertEqual(scan.devices[0].model, "MX Master 2S")
        self.assertTrue(scan.devices[0].writable)
        hidpp.close_devices(scan.devices)

    def test_bt_product_is_read_from_uevent_before_any_request(self):
        with tempfile.TemporaryDirectory() as root:
            device = Path(root) / "hidraw0" / "device"
            device.mkdir(parents=True)
            (device / "uevent").write_text("HID_ID=0005:0000046D:0000B360\nHID_NAME=MX Master 3S\n")
            (device / "report_descriptor").write_bytes(b"\x06\x00\xff\x85\x11")
            nodes = hidpp.find_hidpp_nodes(root)
            self.assertEqual((nodes[0].bus, nodes[0].vendor, nodes[0].product), (5, 0x046D, 0xB360))
            with patch.object(hidpp, "Channel", side_effect=AssertionError("keyboard opened")):
                self.assertEqual(hidpp.scan_devices(nodes).devices, [])

    def test_mx_ergo_trackball_kinds_are_admitted(self):
        receiver = hidpp.HidrawNode("/dev/u", 3, 0x046D, 0xC52B, "receiver")
        bt = hidpp.HidrawNode("/dev/bt", 5, 0x046D, 0xB099, "MX Ergo S")
        channels = {
            "/dev/u": DiscoveryChannel(
                "/dev/u",
                {
                    1: hidpp.PairingInfo(1, "trackball", 0x4999),
                    2: hidpp.PairingInfo(2, "trackball", 0x4998),
                },
                {1: "MX Ergo", 2: "M570"},
            ),
            "/dev/bt": DiscoveryChannel("/dev/bt", names={0xFF: "MX Ergo S"}, direct_type=5),
        }
        with patch.object(hidpp, "Channel", side_effect=lambda path: channels[path]):
            scan = hidpp.scan_devices([receiver, bt])
        self.assertEqual(
            [(d.model, d.kind) for d in scan.devices],
            [("MX Ergo", "trackball"), ("MX Ergo S", "trackball")],
        )
        hidpp.close_devices(scan.devices)

    def test_sleeping_mouse_then_bluetooth_reconnect(self):
        node = hidpp.HidrawNode("/dev/bt", 5, 0x046D, 0xB025, "MX Anywhere 3S")
        asleep = DiscoveryChannel(node.path, sleepy=True)
        awake = DiscoveryChannel(node.path)
        with patch.object(hidpp, "Channel", side_effect=[asleep, awake]):
            first = hidpp.scan_devices([node])
            second = hidpp.scan_devices([node])
        self.assertEqual(first.devices, [])
        self.assertEqual(len(first.sleeping), 1)
        self.assertTrue(asleep.closed)
        self.assertEqual(second.devices[0].model, "MX Anywhere 3S")
        hidpp.close_devices(second.devices)

    def test_family_registry_excludes_keys_and_gaming(self):
        self.assertEqual(devices.model_for("Wireless Mouse MX Master 2S", 0x4069), "MX Master 2S")
        self.assertEqual(devices.model_for("Unknown", 0x4069), "MX Master 2S")
        self.assertIsNone(devices.model_for("MX Keys", 0x408A))
        self.assertIsNone(devices.model_for("G703 LS", 0x4086))
        self.assertFalse(devices.plausible_mouse_name("MX Keys"))
        self.assertEqual(devices.bluetooth_model("unknown", 0xB019), "MX Master 2S")
        self.assertIsNone(devices.bluetooth_model("MX Master 3S", 0xB360))
        self.assertIsNone(devices.bluetooth_model("MX Master Keyboard", 0xB099))
        self.assertIsNone(devices.bluetooth_model("Logitech Mouse M720", 0xB999))


if __name__ == "__main__":
    unittest.main()
