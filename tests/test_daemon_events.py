import os
import socket
import struct
import threading
import unittest

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, packet

from maestro import hidpp
from maestro.daemon.events import (
    Diversion,
    EventChannel,
    IdentityChanged,
    Unidentified,
    decode,
    guard_device,
    is_notification,
    same_endpoint,
)
from maestro.daemon.gestures import Gesture, WheelAccumulator


class DiversionTests(unittest.TestCase):
    def test_reversible_raw_diversion_preserves_other_bits(self):
        device = FakeDevice()
        device.reporting[0xC3] = 0x40
        diversion = Diversion(device)
        diversion.enable(0xC3, raw_xy=True)
        self.assertEqual(device.reporting[0xC3], 0x51)
        self.assertEqual(diversion.owned, {0xC3: True})
        self.assertEqual(diversion.close(), [])
        self.assertEqual(device.reporting[0xC3], 0x40)
        self.assertEqual(diversion.owned, {})
        self.assertEqual(diversion.close(), [])

    def test_timeout_after_write_still_undiverts(self):
        device = FakeDevice()
        diversion = Diversion(device)
        device.fail_enable = True
        with self.assertRaises(hidpp.Timeout):
            diversion.enable(0xC3, True)
        self.assertEqual(device.reporting[0xC3], 0x11)
        diversion.close()
        self.assertEqual(device.reporting[0xC3], 0)

    def test_nonmouse_and_gaming_devices_never_receive_diversion(self):
        for name, kind in (("MX Keys", 0), ("G703", 3), ("MX Master fake", 0)):
            device = FakeDevice(name, kind)
            with self.subTest(name=name), self.assertRaises(ValueError):
                Diversion(device)
            self.assertFalse(any(f == hidpp.REPROG_CONTROLS_V4 for f, _, _ in device.calls))

    def test_other_owner_and_unsupported_raw_are_rejected(self):
        device = FakeDevice()
        diversion = Diversion(device)
        device.reporting[0xC3] = 1
        with self.assertRaises(RuntimeError):
            diversion.enable(0xC3, True)
        with self.assertRaises(ValueError):
            diversion.enable(0x53, True)
        self.assertFalse(diversion.owned)
        self.assertEqual(device.reporting[0xC3], 1)

    def test_thumb_direction_and_other_bits_are_preserved(self):
        device = FakeDevice()
        device.thumb_mode = [0x80, 1]
        diversion = Diversion(device)
        diversion.thumb(True)
        self.assertEqual(device.thumb_mode, [0x81, 1])
        diversion.close()
        self.assertEqual(device.thumb_mode, [0x80, 1])

    def test_cleanup_attempts_every_control_after_one_failure(self):
        device = FakeDevice()
        diversion = Diversion(device)
        diversion.enable(0xC3, True)
        diversion.enable(0x53)
        original = diversion._set

        def fail(cid, *args):
            if cid == 0xC3:
                raise OSError("disconnected")
            return original(cid, *args)

        diversion._set = fail
        self.assertEqual(len(diversion.close()), 1)
        self.assertEqual(device.reporting[0x53], 0)

    def test_repaired_slot_cannot_send_cleanup_to_a_keyboard(self):
        device = FakeDevice()
        identified = [True]
        diversion = Diversion(device, guard=lambda: identified[0])
        diversion.enable(0xC3, True)
        identified[0] = False
        device.calls.clear()
        with self.assertRaises(IdentityChanged):
            diversion.close()
        self.assertFalse(device.calls)


class UnitGateTests(unittest.TestCase):
    def unit_reads(self, device):
        return [c for c in device.calls if c[0] == hidpp.FW_VERSION]

    def test_every_write_in_a_batch_reads_the_unit_id_first(self):
        device = FakeDevice()
        diversion = Diversion(device)
        device.calls.clear()
        with diversion.gate.batch():
            device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x04\xb0")
            device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x03\xe8")
        self.assertEqual(len(self.unit_reads(device)), 2)

    def test_one_refusal_stops_the_rest_of_the_batch(self):
        device = FakeDevice()
        diversion = Diversion(device)
        device.unit = b"\0\0\0\0"
        device.calls.clear()
        with diversion.gate.batch():
            for _ in range(2):
                with self.assertRaises(Unidentified):
                    device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x04\xb0")
            # Even once the ID reads again, the stopped batch stays stopped.
            device.unit = FakeDevice().unit
            with self.assertRaises(Unidentified):
                device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x04\xb0")
        self.assertEqual(len(self.unit_reads(device)), 1)
        self.assertFalse([c for c in device.calls if hidpp.is_write(*c[:2])])
        # A new batch (or a single write) checks afresh.
        device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x04\xb0")
        self.assertEqual(device.dpi, 1200)


class SwapChannel:
    """In-memory channel for a real hidpp.Device: mouse A answers until the
    ROOT feature lookup, then mouse B takes the slot."""

    FEATURES = {hidpp.FW_VERSION: 2, hidpp.ADJUSTABLE_DPI: 5}

    def __init__(self, b_unit):
        self.unit = b"\x11\x22\x33\x44"
        self.b_unit = b_unit
        self.log = []

    def request(self, index, idx, function, params=b"", timeout=1.0):
        if idx == 0 and function == 0:
            feature = int.from_bytes(params[:2], "big")
            if feature == hidpp.ADJUSTABLE_DPI:
                self.unit = self.b_unit  # the swap happens during this lookup
            return bytes([self.FEATURES.get(feature, 0)]) + bytes(15)
        if idx == self.FEATURES[hidpp.FW_VERSION]:
            self.log.append(("id", self.unit))
            return b"\x01" + self.unit + bytes(11)
        self.log.append(("write" if (idx, function) == (5, 3) else "other", self.unit))
        return bytes(16)


class FeatureLookupSwapTests(unittest.TestCase):
    def test_identity_is_checked_after_the_feature_lookup(self):
        for b_unit in (b"\x55\x66\x77\x88", b"\0\0\0\0"):
            with self.subTest(b_unit=b_unit):
                channel = SwapChannel(b_unit)
                device = hidpp.Device(channel, 1, SimpleNode(), model="MX Master 2S")
                device.has(hidpp.FW_VERSION)
                gate = guard_device(device)
                self.assertIsNotNone(gate.expected)
                with self.assertRaises((IdentityChanged, Unidentified)):
                    device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x04\xb0")
                self.assertNotIn("write", [kind for kind, _ in channel.log])

    def test_a_normal_mouse_still_gets_the_write(self):
        channel = SwapChannel(b"\x11\x22\x33\x44")
        device = hidpp.Device(channel, 1, SimpleNode(), model="MX Master 2S")
        guard_device(device)
        device.call(hidpp.ADJUSTABLE_DPI, 3, b"\0\x04\xb0")
        self.assertEqual(channel.log[-2:], [("id", channel.unit), ("write", channel.unit)])


class SimpleNode:
    connection = "unifying"


class GestureTests(unittest.TestCase):
    def test_direction_thresholds_and_tap(self):
        for delta, expected in (
            ((49, 0), "tap"),
            ((50, 0), "right"),
            ((-60, 20), "left"),
            ((2, -60), "up"),
            ((2, 60), "down"),
            ((50, 50), "down"),
        ):
            with self.subTest(delta=delta):
                gesture = Gesture(50)
                gesture.begin()
                gesture.move(*delta)
                self.assertEqual(gesture.end(), expected)
                self.assertIsNone(gesture.end())

    def test_accumulation_latches_first_direction(self):
        gesture = Gesture(50)
        gesture.move(500, 0)
        gesture.begin()
        gesture.move(30, 0)
        gesture.move(20, 0)
        gesture.move(-500, 500)
        self.assertEqual(gesture.end(), "right")
        gesture.begin()
        self.assertEqual(gesture.end(), "tap")

    def test_wheel_fraction_reversal_and_stroke_start(self):
        wheel = WheelAccumulator(120)
        self.assertEqual(wheel.feed(70), 0)
        self.assertEqual(wheel.feed(60), 1)
        self.assertEqual(wheel.remainder, 10)
        self.assertEqual(wheel.feed(-120), 0)
        self.assertEqual(wheel.feed(-10), -1)
        self.assertEqual(wheel.feed(359), 2)
        self.assertEqual(wheel.feed(1, start=True), 0)
        self.assertEqual(wheel.remainder, 1)
        self.assertEqual(wheel.feed(32767), 32)


class StreamTests(unittest.TestCase):
    def test_preserves_notifications_in_drain_and_during_reply(self):
        host, hardware = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        host.setblocking(False)
        original = hidpp.Channel.__new__(hidpp.Channel)
        original.fd, original.path, original._swid = host.detach(), "fake", 0
        channel = EventChannel.take(original)
        self.addCleanup(channel.close)
        self.addCleanup(hardware.close)
        first = packet(2, 0, struct.pack("!4H", 0xC3, 0, 0, 0))
        second = packet(2, 0x10, struct.pack("!hh", -51, 10))
        hardware.send(first)

        def responder():
            query = hardware.recv(64)
            hardware.send(second)
            hardware.send(query[:4] + b"reply".ljust(16, b"\0"))

        thread = threading.Thread(target=responder)
        thread.start()
        self.assertEqual(channel.request(1, 2, 2)[:5], b"reply")
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(channel.read_events(), [first, second])
        self.assertEqual(original.fd, -1)

    def test_decode_exact_device_features_and_connection_flags(self):
        device = FakeDevice()
        indexes = device.features
        self.assertEqual(
            decode(packet(2, 0, struct.pack("!4H", 0xC3, 0x53, 0, 0)), device, indexes),
            ("buttons", {0xC3, 0x53}),
        )
        self.assertEqual(
            decode(packet(2, 0x10, struct.pack("!hh", -40, 80)), device, indexes),
            ("move", (-40, 80)),
        )
        self.assertEqual(
            decode(packet(3, 0, b"\xff\x88\0\0\x02"), device, indexes), ("thumb", (-120, False))
        )
        self.assertEqual(
            decode(packet(0x41, 4, b"\x40\x69\x40", short=True), device, indexes),
            ("disconnected", None),
        )
        self.assertEqual(
            decode(packet(0x41, 4, b"\x00\x69\x40", short=True), device, indexes),
            ("reconnect", None),
        )
        self.assertEqual(decode(packet(4, 0, b"\0\1\1"), device, indexes), ("reconnect", None))
        self.assertIsNone(decode(packet(2, 0, b"\0" * 8, index=2), device, indexes))
        self.assertFalse(is_notification(packet(2, 1, b"\0" * 8)))
        self.assertIsNone(decode(b"\x11", device, indexes))

    def test_queue_overflow_fails_closed_instead_of_dropping_a_release(self):
        host, hardware = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        original = hidpp.Channel.__new__(hidpp.Channel)
        original.fd, original.path, original._swid = host.detach(), "fake", 0
        os.set_blocking(original.fd, False)
        channel = EventChannel.take(original)
        self.addCleanup(channel.close)
        self.addCleanup(hardware.close)
        report = packet(2, 0, b"\0" * 8)
        for _ in range(4097):
            channel._capture(report)
        with self.assertRaisesRegex(OSError, "overflow"):
            channel.read_events()


class DiscoveryTests(unittest.TestCase):
    def test_endpoint_guard_uses_pairing_kind_and_product_not_system_name(self):
        device = FakeDevice()
        pair = hidpp.PairingInfo(1, "mouse", 0x4069)
        device.channel.pairing_info = lambda *a: pair
        self.assertTrue(same_endpoint(device))
        pair = hidpp.PairingInfo(1, "keyboard", 0x408A)
        self.assertFalse(same_endpoint(device))
        pair = hidpp.PairingInfo(1, "mouse", 0x405E)
        self.assertFalse(same_endpoint(device))

    def test_read_only_identity_rejects_every_diversion_write(self):
        device = FakeDevice(writable=False)
        diversion = Diversion(device)
        device.calls.clear()
        with self.assertRaisesRegex(ValueError, "writes are disabled"):
            diversion.enable(0xC3, True)
        with self.assertRaisesRegex(ValueError, "writes are disabled"):
            diversion.thumb(True)
        self.assertEqual(diversion.close(), [])
        self.assertFalse(device.calls)
