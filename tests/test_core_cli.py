"""CLI selection and unknown-mouse behavior without hardware."""

import contextlib
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro import __main__ as cli
from maestro import hidpp, mouse


class FakeMouse:
    def __init__(self, name, model, path, index):
        self._name = name
        self.model = model
        self.kind = "mouse"
        self.node = hidpp.HidrawNode(path, 3, 0x046D, 0xC52B, "receiver")
        self.index = index
        self.wpid = None
        self.version = (4, 5)

    def name(self):
        return self._name

    def has(self, feature):
        return False

    def feature_details(self):
        return [{"id": "0x0000", "version": 0}]


class CliCoreTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.known = FakeMouse("MX Master 2S", "MX Master 2S", "/dev/u", 1)
        self.unknown = FakeMouse("Logitech Mouse M720", None, "/dev/u", 2)
        self.find = stack.enter_context(
            patch.object(mouse, "find_mice", return_value=[self.known, self.unknown])
        )
        stack.enter_context(patch.object(mouse, "last_scan", hidpp.ScanResult()))
        # These fakes have no unit ID; treat it as read (see test_daemon_cli for the gate).
        stack.enter_context(
            patch.object(cli, "guard_device", return_value=SimpleNamespace(expected="unit"))
        )
        stack.enter_context(patch.object(hidpp, "close_devices"))
        self.stdout = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.stderr = stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def test_status_all_marks_unknown_unsupported(self):
        self.assertEqual(cli.main(["status", "--all"]), 0)
        self.assertIn("Logitech Mouse M720", self.stdout.getvalue())
        self.assertIn("unsupported", self.stdout.getvalue())
        self.find.assert_called_once_with(include_unsupported=True)

    def test_select_by_name_path_and_slot(self):
        for argv, expected in (
            (["--device", "master", "status", "--json"], "MX Master 2S"),
            (["status", "--device", "/dev/u:2", "--json"], "Logitech Mouse M720"),
            (["--mouse", "1", "status", "--json"], "Logitech Mouse M720"),
        ):
            with self.subTest(argv=argv):
                self.stdout.seek(0)
                self.stdout.truncate()
                self.assertEqual(cli.main(argv), 0)
                self.assertEqual(json.loads(self.stdout.getvalue())[0]["name"], expected)

    def test_ambiguous_receiver_path_and_invalid_mouse(self):
        self.assertEqual(cli.main(["status", "--device", "/dev/u"]), 2)
        self.assertIn("matches 2 mice", self.stderr.getvalue())
        self.assertEqual(cli.main(["--mouse", "3", "status"]), 2)

    def test_diagnose_is_shareable_json(self):
        self.assertEqual(cli.main(["diagnose", "--json", "--device", "MX Master"]), 0)
        report = json.loads(self.stdout.getvalue())
        self.assertEqual(report["devices"][0]["model"], "MX Master 2S")
        self.assertEqual(report["devices"][0]["features"], [{"id": "0x0000", "version": 0}])
        self.assertNotIn("serial", self.stdout.getvalue().lower())

    def test_one_numbering_and_unsupported_write_guard(self):
        self.find.return_value = [self.unknown, self.known]
        self.assertEqual(cli.main(["status", "--all"]), 0)
        self.assertIn("[0] Logitech Mouse M720", self.stdout.getvalue())
        self.assertIn("[1] MX Master 2S", self.stdout.getvalue())

        self.stdout.seek(0)
        self.stdout.truncate()
        self.assertEqual(cli.main(["status"]), 0)
        self.assertTrue(self.stdout.getvalue().startswith("[1] MX Master 2S"))

        self.stdout.seek(0)
        self.stdout.truncate()
        self.assertEqual(cli.main(["status", "--json"]), 0)
        self.assertEqual(json.loads(self.stdout.getvalue()), [mouse.status(self.known)])

        with patch.object(mouse, "set_dpi", return_value=1200) as setter:
            self.assertEqual(cli.main(["--mouse", "0", "dpi", "1200"]), 2)
            self.assertIn("unsupported Logitech device", self.stderr.getvalue())
            setter.assert_not_called()

            self.assertEqual(cli.main(["--device", "/dev/u:2", "dpi", "1200"]), 2)
            setter.assert_not_called()

            self.assertEqual(cli.main(["--mouse", "1", "dpi", "1200"]), 0)
            setter.assert_called_once_with(self.known, 1200)

            setter.reset_mock()
            self.assertEqual(cli.main(["dpi", "1200"]), 0)
            setter.assert_called_once_with(self.known, 1200)

    def test_mx_ergo_trackball_is_supported(self):
        ergo = FakeMouse("MX Ergo S", "MX Ergo S", "/dev/u", 3)
        ergo.kind = "trackball"
        self.find.return_value = [ergo]
        self.assertEqual(cli.main(["status", "--json"]), 0)
        self.assertTrue(json.loads(self.stdout.getvalue())[0]["supported"])
        with patch.object(mouse, "set_dpi", return_value=1200) as setter:
            self.assertEqual(cli.main(["dpi", "1200"]), 0)
            setter.assert_called_once_with(ergo, 1200)


if __name__ == "__main__":
    unittest.main()
