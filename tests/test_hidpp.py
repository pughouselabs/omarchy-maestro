"""Tests that run without a mouse: message framing, error handling, DPI list decoding.

Run with: python3 -m unittest discover -s tests
"""

import os
import sys
import unittest
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maestro import hidpp, mouse  # noqa: E402
from maestro.daemon.events import EventChannel  # noqa: E402


class DrainBudgetTests(unittest.TestCase):
    def channel(self, cls=hidpp.Channel):
        channel = cls.__new__(cls)
        channel.fd, channel.path, channel._swid = 123, "fake", 0
        if cls is EventChannel:
            from collections import deque

            channel.notifications, channel.overflow = deque(), False
        return channel

    def test_never_eagain_stream_has_packet_cap_on_both_channels(self):
        for cls in (hidpp.Channel, EventChannel):
            with (
                self.subTest(cls=cls),
                patch.object(hidpp.os, "read", return_value=b"noise") as read,
                patch.object(hidpp.time, "monotonic", return_value=0),
            ):
                with self.assertRaises(hidpp.Timeout):
                    self.channel(cls)._drain()
                self.assertEqual(read.call_count, hidpp.DRAIN_PACKETS)

    def test_drain_has_elapsed_time_cap(self):
        for cls in (hidpp.Channel, EventChannel):
            with (
                self.subTest(cls=cls),
                patch.object(hidpp.os, "read", return_value=b"noise") as read,
                patch.object(hidpp.time, "monotonic", side_effect=[0, 0, 0.051]),
            ):
                with self.assertRaises(hidpp.Timeout):
                    self.channel(cls)._drain()
                self.assertEqual(read.call_count, 1)

    def test_empty_stream_stops_immediately_before_any_write(self):
        for cls in (hidpp.Channel, EventChannel):
            for pairing in (False, True):
                channel = self.channel(cls)
                with (
                    self.subTest(cls=cls, pairing=pairing),
                    patch.object(hidpp.os, "read", return_value=b"") as read,
                    patch.object(hidpp.os, "write") as write,
                ):
                    with self.assertRaisesRegex(hidpp.NoResponse, "closed"):
                        if pairing:
                            channel.pairing_info(1, "unifying")
                        else:
                            channel.request(1, 0, 1)
                    read.assert_called_once()
                    write.assert_not_called()

    def test_request_and_pairing_drain_use_original_deadline(self):
        for pairing in (False, True):
            channel = self.channel()
            with (
                self.subTest(pairing=pairing),
                patch.object(hidpp.time, "monotonic", side_effect=[10, 10, 10, 10.02]),
                patch.object(hidpp.os, "read", side_effect=BlockingIOError),
                patch.object(hidpp.os, "write") as write,
            ):
                with self.assertRaisesRegex(hidpp.Timeout, "expired while draining"):
                    if pairing:
                        channel.pairing_info(1, "unifying", timeout=0.01)
                    else:
                        channel.request(1, 0, 1, timeout=0.01)
                write.assert_not_called()

    def test_daemon_discovery_base_channels_cannot_spin_on_eof(self):
        node = hidpp.HidrawNode("fake", 3, hidpp.LOGITECH_VENDOR, 0xC52B, "receiver")
        with (
            patch.object(hidpp.os, "open", return_value=123),
            patch.object(hidpp.os, "close") as close,
            patch.object(hidpp.os, "read", return_value=b"") as read,
            patch.object(hidpp.os, "write") as write,
        ):
            result = hidpp.scan_devices([node])
            self.assertEqual(result.devices, [])
            self.assertEqual(len(result.errors), 6)
            self.assertEqual(read.call_count, 6)
            write.assert_not_called()
            close.assert_called_once_with(123)

    def test_empty_reply_is_a_closed_channel(self):
        channel = self.channel()
        with (
            patch.object(hidpp.time, "monotonic", return_value=0),
            patch.object(hidpp.select, "select", return_value=([123], [], [])),
            patch.object(hidpp.os, "read", return_value=b"") as read,
        ):
            with self.assertRaisesRegex(hidpp.NoResponse, "closed"):
                channel._read(1)
            read.assert_called_once()


class FakeChannel(hidpp.Channel):
    """A Channel over a socketpair: the test plays the device."""

    def __init__(self, responder):
        import socket

        self._dev_sock, self._host_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self._host_sock.setblocking(False)
        self.fd = self._host_sock.fileno()
        self.path = "fake"
        self._swid = 0
        self.responder = responder
        self.sent = []

    def request(self, *args, **kwargs):
        # Answer whatever request goes out before the real request() reads.
        original_write = os.write

        def write(fd, data):
            n = original_write(fd, data)
            self.sent.append(bytes(data))
            for reply in self.responder(bytes(data)):
                self._dev_sock.send(reply)
            return n

        os.write = write
        try:
            return super().request(*args, **kwargs)
        finally:
            os.write = original_write

    def close(self):
        self._dev_sock.close()
        self._host_sock.close()


def reply_to(msg, payload, feature=None):
    return bytes([0x11, msg[1], msg[2] if feature is None else feature, msg[3]]) + payload.ljust(
        16, b"\x00"
    )


class FramingTests(unittest.TestCase):
    def test_request_layout_and_reply(self):
        ch = FakeChannel(lambda m: [reply_to(m, b"\x04\x05")])
        out = ch.request(1, 0, 1, b"\x00\x00\x5a")
        sent = ch.sent[0]
        self.assertEqual(len(sent), 20)
        self.assertEqual(sent[:3], b"\x11\x01\x00")
        self.assertEqual(sent[3] >> 4, 1)  # function
        self.assertNotEqual(sent[3] & 0x0F, 0)  # software id never 0
        self.assertEqual(out[:2], b"\x04\x05")
        ch.close()

    def test_ignores_unrelated_traffic(self):
        def responder(m):
            noise = bytes([0x11, 0x02, m[2], m[3]]) + b"\x99" * 16  # other device
            note = bytes([0x11, m[1], m[2], 0x00]) + b"\x77" * 16  # notification
            return [noise, note, reply_to(m, b"\x01")]

        ch = FakeChannel(responder)
        self.assertEqual(ch.request(1, 3, 2)[0], 1)
        ch.close()

    def test_bluetooth_reply_can_use_index_zero(self):
        def responder(m):
            answer = bytearray(reply_to(m, b"\x04\x05"))
            answer[1] = 0
            return [bytes(answer)]

        ch = FakeChannel(responder)
        self.assertEqual(ch.request(hidpp.DIRECT_INDEX, 0, 1)[:2], b"\x04\x05")
        ch.close()

    def test_hidpp20_error(self):
        ch = FakeChannel(lambda m: [bytes([0x11, m[1], 0xFF, m[2], m[3], 0x02]).ljust(20, b"\x00")])
        with self.assertRaisesRegex(hidpp.HidppError, "invalid argument"):
            ch.request(1, 5, 3, b"\x00")
        ch.close()

    def test_hidpp10_error_means_unreachable(self):
        ch = FakeChannel(lambda m: [bytes([0x10, m[1], 0x8F, m[2], m[3], 0x09, 0x00])])
        with self.assertRaises(hidpp.NoResponse):
            ch.request(3, 0, 1)
        ch.close()

    def test_timeout(self):
        ch = FakeChannel(lambda m: [])
        with self.assertRaises(hidpp.Timeout):
            ch.request(1, 0, 1, timeout=0.05)
        ch.close()

    def test_sleepy_device_gets_a_second_chance(self):
        calls = []

        def responder(m):
            calls.append(m)
            return [] if len(calls) == 1 else [reply_to(m, b"\x04\x05")]

        ch = FakeChannel(responder)
        dev = hidpp.Device(ch, 1, None)
        with self.assertRaises(hidpp.Timeout):
            dev.ping(timeout=0.05)
        self.assertEqual(dev.ping(timeout=0.5), (4, 5))
        ch.close()


class WriteGuardTests(unittest.TestCase):
    """Device.call runs write_guard before anything that is not a known read."""

    def device(self, guard):
        sent = []
        channel = type(
            "Channel", (), {"request": lambda self, *args, **kwargs: sent.append(args) or b"\1"}
        )()
        node = hidpp.HidrawNode("/dev/fake", 3, 0x46D, 0xC52B, "receiver")
        device = hidpp.Device(channel, 1, node, write_guard=guard)
        device._features.update({hidpp.ADJUSTABLE_DPI: 5, hidpp.CHANGE_HOST: 6, 0x9999: 7})
        return device, sent

    def test_reads_pass_and_every_other_call_is_checked_first(self):
        checked = []

        def refuse(device, feature, function):
            checked.append((feature, function))
            raise hidpp.NoResponse("refused")

        device, sent = self.device(refuse)
        device.call(hidpp.ADJUSTABLE_DPI, 2)
        device.call(hidpp.CHANGE_HOST, 0)
        self.assertEqual(len(sent), 2)
        for feature, function in ((hidpp.ADJUSTABLE_DPI, 3), (hidpp.CHANGE_HOST, 1), (0x9999, 0)):
            with self.assertRaises(hidpp.NoResponse):
                device.call(feature, function, b"\0")
        self.assertEqual(len(sent), 2)
        self.assertEqual(checked, [(hidpp.ADJUSTABLE_DPI, 3), (hidpp.CHANGE_HOST, 1), (0x9999, 0)])

    def test_without_a_guard_writes_are_refused_and_reads_are_sent(self):
        device, sent = self.device(None)
        for feature, function in ((hidpp.ADJUSTABLE_DPI, 3), (hidpp.CHANGE_HOST, 1), (0x9999, 0)):
            with self.assertRaises(hidpp.Unguarded):
                device.call(feature, function, b"\0")
        self.assertEqual(sent, [])
        device.call(hidpp.ADJUSTABLE_DPI, 2)
        self.assertEqual(len(sent), 1)


class DpiListTests(unittest.TestCase):
    def test_range_with_step(self):
        data = (
            (200).to_bytes(2, "big")
            + (0xE000 | 50).to_bytes(2, "big")
            + (4000).to_bytes(2, "big")
            + b"\x00\x00"
        )
        values, step = mouse.parse_dpi_list(data)
        self.assertEqual(step, 50)
        self.assertEqual(values[0], 200)
        self.assertEqual(values[-1], 4000)
        self.assertEqual(len(values), 77)  # matches the MX Master 2S

    def test_plain_list(self):
        data = b"".join(v.to_bytes(2, "big") for v in (400, 800, 1600)) + b"\x00\x00"
        self.assertEqual(mouse.parse_dpi_list(data), ([400, 800, 1600], None))


class SupportTests(unittest.TestCase):
    def test_supported_names(self):
        for name in (
            "Wireless Mouse MX Master 2S",
            "MX Master 3S",
            "MX Master 4",
            "MX Master 3 for Mac",
            "MX Anywhere 3",
            "MX Vertical",
            "MX Ergo S",
        ):
            self.assertTrue(mouse.is_supported(name), name)
        for name in ("MX Keys", "G703 LS", "M720 Triathlon"):
            self.assertFalse(mouse.is_supported(name), name)
        self.assertFalse(mouse.is_supported("MX Master 2S", kind="keyboard"))


if __name__ == "__main__":
    unittest.main()
