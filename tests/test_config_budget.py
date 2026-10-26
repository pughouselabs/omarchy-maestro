"""The same expanded budget protects disk, backups, stdin, and IPC responses."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import isolation  # noqa: F401
from daemon_fakes import FakeDevice, FakeOutput

from maestro import __main__ as cli
from maestro.daemon import config as cfg
from maestro.daemon.actions import Actions
from maestro.daemon.ipc import MAX_MESSAGE
from maestro.daemon.service import Daemon, MouseSession


class ConfigBudgetTests(unittest.TestCase):
    def near_limit(self):
        # Escaped Unicode and defaults count toward the encoded byte budget.
        raw = {"profiles": []}
        while True:
            candidate = json.loads(json.dumps(raw))
            candidate["profiles"].append({"name": "é" * 180, "match": {"class": "x" * 500}})
            try:
                cfg.validate(candidate)
            except cfg.ConfigError:
                return raw, candidate
            raw = candidate

    def test_largest_accepted_config_fits_full_ipc_and_roundtrips_offline(self):
        raw, oversized = self.near_limit()
        self.assertGreater(len(raw["profiles"]), 10)
        self.assertLessEqual(
            len(json.dumps({"ok": True, "config": cfg.full_config(raw)}).encode()) + 1, MAX_MESSAGE
        )
        with tempfile.TemporaryDirectory() as directory:
            config = cfg.ConfigFile(Path(directory) / "config.json")
            config.apply(raw)
            self.assertEqual(cfg.ConfigFile(config.path).raw, raw)
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            self.addCleanup(daemon.close)
            self.assertTrue(daemon.handle({"op": "config_apply", "config": raw})["ok"])
            self.assertEqual(daemon.handle({"op": "config_get"})["config"], cfg.full_config(raw))
            before = config.path.read_bytes()
            backups = config.backups()
            for operation in (
                config.apply,
                config.replace,
                lambda value: daemon.handle({"op": "config_apply", "config": value}),
            ):
                with self.assertRaises(cfg.ConfigError):
                    operation(oversized)
                self.assertEqual(config.path.read_bytes(), before)
                self.assertEqual(config.backups(), backups)

    def largest_resolved(self):
        """An accepted config whose bulk lands in every mouse's resolved options."""
        raw = {"buttons": {}}
        for name in ("back", "forward", "middle", "mode_shift", "gesture"):
            argv = []
            while True:
                argv.append("é" * 160)
                candidate = json.loads(json.dumps(raw))
                candidate["buttons"][name] = {"type": "command", "argv": list(argv)}
                try:
                    cfg.validate(candidate)
                except cfg.ConfigError:
                    return raw
                raw = candidate
                if len(argv) == cfg.MAX_ARGV:
                    break
        return raw

    def test_largest_accepted_config_with_two_mice_fits_every_app_response(self):
        raw = self.largest_resolved()
        full = len((json.dumps(cfg.full_config(raw), indent=2) + "\n").encode())
        self.assertGreater(full, cfg.MAX_CONFIG_BYTES - 1024)
        with tempfile.TemporaryDirectory() as directory:
            config = cfg.ConfigFile(Path(directory) / "config.json")
            config.apply(raw)
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            self.addCleanup(daemon.close)
            for index, unit in ((1, b"\x01\x02\x03\x04"), (2, b"\x05\x06\x07\x08")):
                device = FakeDevice()
                device.index, device.unit = index, unit
                session = MouseSession(device, daemon.actions, ledger=daemon.ledger)
                daemon.sessions.append(session)
                daemon.devices.append(device)
                session.configure(daemon.options(session))

            def exchange(message):
                response = daemon.handle(json.loads(json.dumps(message)))
                encoded = json.dumps(response).encode() + b"\n"
                self.assertLessEqual(len(encoded), MAX_MESSAGE, message)
                return json.loads(encoded)

            listing = exchange({"op": "controls"})
            self.assertEqual(len(listing["devices"]), 2)
            self.assertTrue(all("options" not in d for d in listing["devices"]))
            for number in (0, 1):
                one = exchange({"op": "controls", "device": number})["devices"]
                self.assertEqual([d["device"] for d in one], [number])
                self.assertEqual(one[0]["options"]["buttons"], raw["buttons"])
            self.assertLessEqual(
                len(json.dumps(exchange({"op": "config_get"})).encode()) + 1, MAX_MESSAGE
            )
            # The settings app reads each command's stdout with the same limit.
            with (
                patch.object(cli.ipc, "request_if_running", side_effect=exchange),
                patch.object(cli.mouse, "find_mice") as direct,
            ):
                for argv in (
                    ["controls", "--json"],
                    ["controls", "--mouse", "0", "--json"],
                    ["controls", "--mouse", "1", "--json"],
                    ["config", "get"],
                ):
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        self.assertEqual(cli.main(argv), 0)
                    self.assertLessEqual(len(out.getvalue()), 65536, argv)
                direct.assert_not_called()

    def test_budget_includes_defaults(self):
        raw, _ = self.near_limit()
        # Fill a valid profile match until the raw object fits but defaults do not.
        for size in range(1, 1025):
            raw["profiles"][0]["match"]["title"] = "x" * size
            raw_size = len((json.dumps(raw, indent=2) + "\n").encode())
            full_size = len((json.dumps(cfg.full_config(raw), indent=2) + "\n").encode())
            if raw_size <= cfg.MAX_CONFIG_BYTES < full_size:
                with self.assertRaisesRegex(cfg.ConfigError, "including defaults"):
                    cfg.validate(raw)
                return
        self.fail("no boundary candidate found")

    def test_bounded_read_precedes_parse_and_keeps_last_good(self):
        with tempfile.TemporaryDirectory() as directory:
            config = cfg.ConfigFile(Path(directory) / "config.json")
            config.apply({"settings": {"dpi": 1000}})
            config.path.write_bytes(b"{}" + b" " * cfg.MAX_CONFIG_BYTES)
            with patch.object(cfg.json, "loads", side_effect=AssertionError("must not parse")):
                self.assertFalse(config.reload())
            self.assertEqual(config.raw, {"settings": {"dpi": 1000}})
            self.assertIn("move the oversized file aside", config.error)
            stream = io.BytesIO(b" " * (cfg.MAX_CONFIG_BYTES * 4))
            with self.assertRaises(cfg.ConfigError):
                cfg.read_config(stream)
            self.assertEqual(stream.tell(), cfg.MAX_CONFIG_BYTES + 1)

    def test_oversized_backup_restore_and_undo_preserve_disk_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            config = cfg.ConfigFile(Path(directory) / "config.json")
            config.apply({"settings": {"dpi": 1000}})
            backup = config.backups()[0]["name"]
            path = config.backup_dir / (backup + ".json")
            path.write_bytes(b"{}" + b" " * cfg.MAX_CONFIG_BYTES)
            before = config.path.read_bytes()
            for operation in (lambda: config.restore(backup), config.undo):
                with self.assertRaises(cfg.ConfigError):
                    operation()
                self.assertEqual(config.path.read_bytes(), before)
                self.assertEqual(config.raw, {"settings": {"dpi": 1000}})
                self.assertTrue(path.exists())

    def test_offline_get_and_apply_stdin_reject_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_bytes(b" " * (cfg.MAX_CONFIG_BYTES + 1))
            with (
                patch.object(cli.ipc, "request_if_running", return_value=None),
                patch.object(cli, "ConfigFile", side_effect=lambda: cfg.ConfigFile(path)),
            ):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(cli.main(["config", "get"]), 1)
                self.assertIn("budget", json.loads(out.getvalue())["errors"][0]["message"])
            stream = io.StringIO(" " * (cfg.MAX_CONFIG_BYTES * 2))
            with patch.object(cli.sys, "stdin", stream), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["config", "apply", "--stdin"]), 1)
            self.assertEqual(stream.tell(), cfg.MAX_CONFIG_BYTES + 1)

    def test_count_label_argument_and_total_step_limits(self):
        cases = [
            {"profiles": [{"match": {"class": "*"}}] * (cfg.MAX_PROFILES + 1)},
            {"devices": [{"match": {"name": "*"}}] * (cfg.MAX_DEVICES + 1)},
            {
                "automations": {
                    f"a-{i}": {
                        "name": "a",
                        "description": "b",
                        "steps": [{"type": "delay", "ms": 0}],
                    }
                    for i in range(cfg.MAX_AUTOMATIONS + 1)
                }
            },
            {"profiles": [{"name": "a" * (cfg.MAX_LABEL + 1), "match": {"class": "*"}}]},
            {"buttons": {"back": {"type": "command", "argv": ["a" * (cfg.MAX_ARGUMENT + 1)]}}},
            {"buttons": {"back": {"type": "command", "argv": ["a"] * (cfg.MAX_ARGV + 1)}}},
            {
                "automations": {
                    f"a-{i}": {
                        "name": "a",
                        "description": "b",
                        "steps": [{"type": "delay", "ms": 0}] * 50,
                    }
                    for i in range(6)
                }
            },
        ]
        for raw in cases:
            with self.subTest(fields=list(raw)), self.assertRaises(cfg.ConfigError):
                cfg.validate(raw)
