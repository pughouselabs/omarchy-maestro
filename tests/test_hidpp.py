"""Tests that run without a mouse: message framing, error handling, DPI list decoding.

Run with: python3 -m unittest discover -s tests
"""

import os
import sys
import unittest

import isolation  # noqa: F401  (private runtime and config dirs)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from maestro import hidpp, mouse  # noqa: E402


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
