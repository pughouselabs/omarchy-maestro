"""Wheel mode and CLI tests without hardware."""

import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro import __main__ as cli
from maestro import hidpp, mouse


class FakeDevice:
    def __init__(self, flags, supported=True):
        self.flags = flags
        self.supported = supported
        self.calls = []

    def has(self, feature):
        assert feature == hidpp.HIRES_WHEEL
        return self.supported

    def call(self, feature, function, params=b""):
        assert feature == hidpp.HIRES_WHEEL
        self.calls.append((function, params))
        if function == 2:
            self.flags = params[0]
        else:
            assert function == 1
        return bytes([self.flags])


class WheelTests(unittest.TestCase):
    def test_invert_preserves_every_other_bit(self):
        for flags in range(256):
            for inverted in (False, True):
                with self.subTest(flags=flags, inverted=inverted):
                    dev = FakeDevice(flags)
                    result = mouse.set_wheel(dev, inverted)
                    expected = flags | 4 if inverted else flags & ~4
                    self.assertEqual(dev.calls, [(1, b""), (2, bytes([expected])), (1, b"")])
                    self.assertEqual(dev.flags, expected)
                    self.assertEqual(
                        result, mouse.Wheel(bool(flags & 2), inverted, bool(flags & 1))
                    )

    def test_none_does_not_write(self):
        dev = FakeDevice(7)
        self.assertEqual(mouse.set_wheel(dev), mouse.Wheel(True, True, True))
        self.assertEqual(dev.calls, [(1, b""), (1, b"")])

    def test_missing_feature(self):
        dev = FakeDevice(0, supported=False)
        with self.assertRaises(hidpp.HidppError):
            mouse.set_wheel(dev, True)
        self.assertEqual(dev.calls, [])


class CliTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.dev = SimpleNamespace(model="MX Master 2S", kind="mouse")
        self.find = stack.enter_context(patch.object(mouse, "find_mice", return_value=[self.dev]))
        self.close = stack.enter_context(patch.object(hidpp, "close_devices"))
        self.stdout = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stderr = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def test_scroll_directions(self):
        for value, expected in (("on", "inverted"), ("off", "normal")):
            with (
                self.subTest(value=value),
                patch.object(
                    mouse, "set_wheel", return_value=mouse.Wheel(True, value == "on", False)
                ) as setter,
            ):
                self.stdout.seek(0)
                self.stdout.truncate()
                self.assertEqual(cli.main(["scroll", "--invert", value]), 0)
                setter.assert_called_once_with(self.dev, inverted=value == "on")
                self.assertEqual(self.stdout.getvalue(), expected + "\n")
        self.close.assert_called_with([self.dev])

    def test_json_for_every_write_command(self):
        snapshot = {"name": "MX Master 2S", "wheel": {"inverted": True}, "dpi": {"current": 1200}}
        cases = [
            (["dpi", "1200"], "set_dpi", 1200),
            (
                ["smartshift", "--mode", "ratchet"],
                "set_smartshift",
                mouse.SmartShift("ratchet", 20, False),
            ),
            (["scroll", "--invert", "on"], "set_wheel", mouse.Wheel(True, True, False)),
            (["scroll", "--invert", "off"], "set_wheel", mouse.Wheel(True, False, False)),
        ]
        for args, setter_name, result in cases:
            with (
                self.subTest(args=args),
                patch.object(mouse, setter_name, return_value=result) as setter,
                patch.object(mouse, "status", return_value=snapshot) as status,
            ):
                self.stdout.seek(0)
                self.stdout.truncate()
                self.assertEqual(cli.main(args + ["--json"]), 0)
                setter.assert_called_once()
                status.assert_called_once_with(self.dev)
                self.assertEqual(json.loads(self.stdout.getvalue()), snapshot)

    def test_existing_plain_output(self):
        for args, setter_name, result, expected in [
            (["dpi", "1200"], "set_dpi", 1200, "1200\n"),
            (
                ["smartshift", "--threshold", "20"],
                "set_smartshift",
                mouse.SmartShift("ratchet", 20, False),
                "ratchet 20\n",
            ),
        ]:
            with (
                self.subTest(args=args),
                patch.object(mouse, setter_name, return_value=result),
                patch.object(mouse, "status") as status,
            ):
                self.stdout.seek(0)
                self.stdout.truncate()
                self.assertEqual(cli.main(args), 0)
                self.assertEqual(self.stdout.getvalue(), expected)
                status.assert_not_called()

    def test_invalid_scroll_arguments(self):
        for args in (["scroll"], ["scroll", "--invert", "yes"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                cli.main(args)
            self.assertEqual(error.exception.code, 2)
        self.find.assert_not_called()

    def test_scroll_no_mouse(self):
        self.find.return_value = []
        self.assertEqual(cli.main(["scroll", "--invert", "on"]), 2)

    def test_scroll_invalid_mouse(self):
        self.assertEqual(cli.main(["--mouse", "1", "scroll", "--invert", "on"]), 2)

    def test_scroll_device_errors(self):
        for error in (hidpp.HidppError("unsupported"), hidpp.NoResponse("asleep")):
            with self.subTest(error=error), patch.object(mouse, "set_wheel", side_effect=error):
                self.assertEqual(cli.main(["scroll", "--invert", "on"]), 1)
        self.close.assert_called_with([self.dev])


if __name__ == "__main__":
    unittest.main()
