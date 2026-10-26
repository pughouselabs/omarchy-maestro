"""Settings-app engine contract without a real mouse or user configuration."""

import contextlib
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import isolation  # noqa: F401  (private runtime and config dirs)
from daemon_fakes import FakeDevice, FakeOutput

from maestro import __main__ as cli
from maestro import mouse
from maestro.daemon.actions import Actions
from maestro.daemon.catalog import catalog, control_device
from maestro.daemon.config import ConfigError, ConfigFile, full_config, validate, validate_action
from maestro.daemon.hyprland import build_dispatch
from maestro.daemon.input_owner import InputOwner
from maestro.daemon.ipc import Server
from maestro.daemon.profiles import resolve
from maestro.daemon.service import Daemon, MouseSession
from maestro.daemon.uinput import text_codes


class Validators(unittest.TestCase):
    def test_each_new_action_and_step_bound(self):
        good = {"type": "hyprland", "dispatcher": "workspace", "arg": "e+1"}
        validate_action(good, "action")
        self.assertEqual(build_dispatch(good), 'hl.dsp.focus({workspace="e+1"})')
        self.assertEqual(
            build_dispatch({"type": "hyprland", "dispatcher": "togglefloating"}),
            'hl.dsp.window.float({action="toggle"})',
        )
        self.assertEqual(
            build_dispatch({"type": "hyprland", "dispatcher": "killactive"}),
            "hl.dsp.window.close()",
        )
        for action in (
            {"type": "hyprland", "dispatch": "hl.dsp.focus()"},
            {"type": "hyprland", "dispatcher": "exec", "arg": "id"},
            {"type": "hyprland", "dispatcher": "workspace", "arg": 'e+1";os.execute("id")'},
            {"type": "hyprland", "dispatcher": "workspace", "arg": "e+1\n"},
            {"type": "hyprland", "dispatcher": "workspace", "arg": "e+100"},
            {"type": "hyprland", "dispatcher": "fullscreen", "arg": "anything"},
            {"type": "hyprland", "dispatcher": "focuswindow", "arg": 'class:foo")'},
        ):
            with self.subTest(action=action), self.assertRaises(ConfigError):
                validate_action(action, "action")
            with self.assertRaises(ValueError):
                build_dispatch(action)
        for action, path in (
            ({"type": "sequence", "steps": []}, "steps"),
            ({"type": "sequence", "steps": [{"type": "delay", "ms": 0}] * 51}, "steps"),
            ({"type": "sequence", "steps": [{"type": "delay", "ms": 5001}]}, "ms"),
            ({"type": "sequence", "steps": [None]}, "steps[0]"),
            ({"type": "sequence", "steps": [{"type": "delay", "ms": 5000}] * 7}, "steps"),
            ({"type": "sequence", "steps": [{"type": "text", "text": "x" * 501}]}, "text"),
            ({"type": "sequence", "steps": [{"type": "text", "text": "caf\u00e9"}]}, "text"),
            ({"type": "sequence", "steps": [{"type": "text", "text": "line\n"}]}, "text"),
            ({"type": "automation", "id": "missing"}, "id"),
        ):
            with self.subTest(action=action), self.assertRaises(ConfigError) as error:
                validate_action(action, "action", {})
            self.assertIn(path, str(error.exception))
        self.assertEqual(len(text_codes("Az 9!?")), 6)
        self.assertEqual(len(text_codes("".join(chr(code) for code in range(32, 127)))), 95)

    def test_hyprland_dispatcher_must_be_a_string(self):
        for dispatcher in ([], {}, 4, None, True):
            action = {"type": "hyprland", "dispatcher": dispatcher}
            with self.subTest(dispatcher=dispatcher):
                with self.assertRaises(ValueError):
                    build_dispatch(action)
                with self.assertRaises(ConfigError):
                    validate_action(action, "action")

    def test_automation_references_cycles_and_all_mapping_locations(self):
        valid = {
            "automations": {
                "first": {
                    "name": "First",
                    "description": "Calls second",
                    "steps": [{"type": "automation", "id": "second"}],
                },
                "second": {
                    "name": "Second",
                    "description": "Sends text",
                    "steps": [{"type": "text", "text": "Hello!"}],
                },
            },
            "buttons": {"back": {"type": "automation", "id": "first"}},
            "gesture": {
                "tap": {"type": "sequence", "steps": [{"type": "key", "keys": ["CTRL", "V"]}]}
            },
            "profiles": [
                {
                    "match": {"class": "*"},
                    "buttons": {"middle": {"type": "automation", "id": "second"}},
                }
            ],
        }
        validate(valid)
        valid["automations"]["second"]["steps"] = [{"type": "automation", "id": "first"}]
        with self.assertRaisesRegex(ConfigError, "cycle"):
            validate(valid)
        valid["automations"]["second"]["steps"] = [{"type": "automation", "id": "unknown"}]
        with self.assertRaisesRegex(ConfigError, "unknown automation id"):
            validate(valid)

    def test_expanded_limits_reject_nested_overruns(self):
        def automation(steps):
            return {"name": "Example", "description": "Example", "steps": steps}

        key_step = {"type": "key", "keys": ["A"]}
        refs = [{"type": "automation", "id": ident} for ident in ("a", "b")]
        base = {
            "automations": {"a": automation([key_step] * 26), "b": automation([key_step] * 26)},
            "buttons": {"back": {"type": "sequence", "steps": refs}},
        }
        with self.assertRaisesRegex(ConfigError, "expanded sequence exceeds 50"):
            validate(base)
        base["automations"]["a"]["steps"] = [{"type": "text", "text": "a" * 300}]
        base["automations"]["b"]["steps"] = [{"type": "text", "text": "b" * 300}]
        with self.assertRaisesRegex(ConfigError, "text exceeds 500"):
            validate(base)
        base["automations"]["a"]["steps"] = [{"type": "delay", "ms": 5000}] * 5
        base["automations"]["b"]["steps"] = [{"type": "delay", "ms": 5000}] * 2
        with self.assertRaisesRegex(ConfigError, "delays exceed 30000"):
            validate(base)
        chain = {
            ident: automation([{"type": "automation", "id": next_id}])
            for ident, next_id in (("a", "b"), ("b", "c"), ("c", "d"))
        }
        chain["d"] = automation([key_step])
        with self.assertRaisesRegex(ConfigError, "nesting exceeds 3"):
            validate({"automations": chain})

    def test_catalog_defaults_are_independent_valid_engine_defaults(self):
        first = catalog()["defaults"]
        self.assertEqual(first, full_config({}))
        self.assertEqual(validate(first), first)
        first["gesture"]["threshold"] = 999
        first["profiles"].append({"name": "Changed"})
        self.assertEqual(catalog()["defaults"], full_config({}))

    def test_catalog_schema_and_actions(self):
        result = catalog()
        self.assertEqual(result["version"], 1)
        self.assertTrue(
            {"omarchy", "windows", "media", "browser", "editing", "zoom", "mouse"}
            <= {g["id"] for g in result["groups"]}
        )
        ids = set()
        for group in result["groups"]:
            for item in group["actions"]:
                self.assertEqual(set(item), {"id", "label", "description", "action"})
                self.assertNotIn(item["id"], ids)
                ids.add(item["id"])
                validate_action(item["action"], item["id"])
                if group["id"] == "omarchy":
                    self.assertIn(item["action"]["argv"][0], {"omarchy", "hyprpicker"})
                if group["id"] == "windows":
                    self.assertEqual(item["action"]["type"], "hyprland")
        self.assertGreaterEqual(len(ids), 60)
        self.assertEqual(
            {
                "workspace",
                "movetoworkspace",
                "focuswindow",
                "movefocus",
                "fullscreen",
                "togglefloating",
                "killactive",
                "cyclenext",
            },
            {
                item["action"]["dispatcher"]
                for group in result["groups"]
                if group["id"] == "windows"
                for item in group["actions"]
            },
        )
        presets = {preset["id"]: preset for preset in result["gesture_presets"]}
        self.assertTrue({"windows", "workspaces", "media", "zoom"} <= set(presets))
        for preset in presets.values():
            self.assertEqual(set(preset["gesture"]), {"tap", "up", "down", "left", "right"})
            for direction, action in preset["gesture"].items():
                validate_action(action, f"{preset['id']}.{direction}")
        templates = {template["id"]: template for template in result["smart_action_templates"]}
        self.assertTrue(
            {"paste-send", "screenshot-region", "morning-apps", "mute-and-lock"} <= set(templates)
        )
        for template in templates.values():
            validate_action({"type": "sequence", "steps": template["steps"]}, template["id"])
        self.assertEqual(
            templates["screenshot-region"]["steps"][0]["argv"],
            ["omarchy", "capture", "screenshot", "region", "copy"],
        )


class SequenceRunner(unittest.TestCase):
    def wait_done(self, actions):
        end = time.monotonic() + 2
        while actions._runs and time.monotonic() < end:
            time.sleep(0.005)
        self.assertFalse(actions._runs)

    def test_normal_error_and_cancel_release_every_key(self):
        output = FakeOutput()
        actions = Actions(output)
        actions.automations = {
            "one": {
                "steps": [{"type": "key", "keys": ["CTRL", "A"]}, {"type": "text", "text": "Hi!"}]
            }
        }
        actions.execute({"type": "automation", "id": "one"}, trigger="normal")
        self.wait_done(actions)
        self.assertFalse(output.held)

        class FailingOutput(FakeOutput):
            def press(self, code):
                if code == 30:
                    raise OSError("fake input failure")
                super().press(code)

        failed = FailingOutput()
        actions = Actions(failed)
        with self.assertLogs("maestrod", level="ERROR"):
            actions.execute({"type": "sequence", "steps": [{"type": "key", "keys": ["CTRL", "A"]}]})
            self.wait_done(actions)
        self.assertFalse(failed.held)

        actions = Actions(output)
        slow = {
            "type": "sequence",
            "steps": [{"type": "delay", "ms": 5000}, {"type": "key", "keys": ["CTRL"]}],
        }
        start = time.perf_counter()
        actions.execute(slow, owner=self, trigger="cancel")
        self.assertLess(time.perf_counter() - start, 0.2)
        self.assertFalse(actions.start_sequence(slow, owner=self, trigger="cancel"))
        actions.cancel_owner(self)
        self.wait_done(actions)
        self.assertFalse(output.held)
        self.assertNotIn(("press", 29), output.events[-2:])

    def test_hyprland_action_is_one_argv_without_shell(self):
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0)

        action = {"type": "hyprland", "dispatcher": "workspace", "arg": "e+1"}
        validate_action(action, "action")
        Actions(FakeOutput(), run=run).execute(action)
        self.assertEqual(calls[0][0], ["hyprctl", "dispatch", 'hl.dsp.focus({workspace="e+1"})'])
        self.assertNotIn("shell", calls[0][1])

    def test_release_retries_every_key_and_cancel_retries_pending(self):
        class FlakyOutput(FakeOutput):
            failures = {}
            attempts = {}

            def release(self, code):
                self.attempts[code] = self.attempts.get(code, 0) + 1
                if self.failures.get(code, 0):
                    self.failures[code] -= 1
                    raise OSError("transient release failure")
                super().release(code)

        output = FlakyOutput()
        actions = Actions(output)
        release = actions.begin({"type": "key", "keys": ["CTRL", "A"]})
        output.failures = {30: 1, 29: 1}
        with self.assertLogs("maestrod", level="WARNING"):
            release()
        self.assertFalse(output.held)
        release = actions.begin({"type": "key", "keys": ["CTRL", "A"]})
        output.failures = {30: 5}
        with self.assertLogs("maestrod", level="WARNING"):
            self.assertFalse(release())
        end = time.monotonic() + 1
        while output.held and time.monotonic() < end:
            time.sleep(0.01)
        self.assertFalse(output.held)
        self.assertGreaterEqual(output.attempts[30], 6)
        release = actions.begin({"type": "key", "keys": ["CTRL"]})
        output.failures = {29: 5}
        with self.assertLogs("maestrod", level="WARNING"):
            self.assertFalse(release())
        actions.cancel_all()
        end = time.monotonic() + 1
        while output.held and time.monotonic() < end:
            time.sleep(0.01)
        self.assertFalse(output.held)

    def test_concurrent_sequences_are_atomic_on_one_input_thread(self):
        class TracingOutput(FakeOutput):
            def __init__(self):
                super().__init__()
                self.threads = []
                self.leaked_modifier = False

            def press(self, code):
                self.threads.append(threading.current_thread().name)
                if code == 48 and self.held.get(42):
                    self.leaked_modifier = True
                super().press(code)
                if code == 42:
                    time.sleep(0.02)

            def release(self, code):
                self.threads.append(threading.current_thread().name)
                super().release(code)

        output = TracingOutput()
        actions = Actions(output)
        first = {"type": "sequence", "steps": [{"type": "key", "keys": ["SHIFT", "A"]}]}
        second = {"type": "sequence", "steps": [{"type": "key", "keys": ["B"]}]}
        actions.execute(first, trigger="first")
        actions.execute(second, trigger="second")
        self.wait_done(actions)
        actions.wheel("volume", 1, {})
        release = actions.begin({"type": "mouse", "button": "back"})
        release()
        self.assertFalse(output.leaked_modifier)
        self.assertFalse(output.held)
        self.assertEqual(set(output.threads), {"maestro-input"})
        self.assertIn(
            [("press", 42), ("press", 30), ("release", 30), ("release", 42)],
            [output.events[:4], output.events[2:6]],
        )

    def test_concurrent_taps_and_sequences_never_shift_unrelated_key(self):
        class ProbingOutput(FakeOutput):
            wrong = 0

            def press(self, code):
                if code == 48 and self.held.get(42):
                    self.wrong += 1
                super().press(code)
                if code == 42:
                    time.sleep(0.0002)

        output = ProbingOutput()
        actions = Actions(output)
        barrier = threading.Barrier(3)
        failures = []

        def taps():
            try:
                barrier.wait()
                for _ in range(100):
                    actions.execute({"type": "key", "keys": ["SHIFT", "A"]})
            except Exception as exc:
                failures.append(exc)

        def sequences():
            try:
                barrier.wait()
                for index in range(100):
                    actions.execute(
                        {"type": "sequence", "steps": [{"type": "key", "keys": ["B"]}]},
                        trigger=f"sequence-{index}",
                    )
            except Exception as exc:
                failures.append(exc)

        workers = [threading.Thread(target=taps), threading.Thread(target=sequences)]
        for worker in workers:
            worker.start()
        barrier.wait()
        for worker in workers:
            worker.join()
        self.wait_done(actions)
        self.assertEqual(failures, [])
        self.assertEqual(output.wrong, 0)
        self.assertFalse(output.held)

    def test_timed_out_queued_press_never_executes_later(self):
        entered = threading.Event()
        unblock = threading.Event()

        class BlockingOutput(FakeOutput):
            def press(self, code):
                if code == 30:
                    entered.set()
                    unblock.wait(1)
                super().press(code)

        output = BlockingOutput()
        owner = InputOwner(output, request_timeout=0.03)
        worker = threading.Thread(target=lambda: owner.chord([30], 1))
        worker.start()
        self.assertTrue(entered.wait(1))
        with self.assertRaisesRegex(TimeoutError, "did not respond"):
            owner.press([48], 2)
        unblock.set()
        worker.join(1)
        owner.cancel()
        self.assertNotIn(("press", 48), output.events)
        self.assertFalse(output.held)
        owner.close()

    def test_shutdown_destroys_device_after_bounded_release_retries(self):
        class BrokenRelease(FakeOutput):
            def release(self, code):
                raise OSError("permanent release failure")

        output = BrokenRelease()
        owner = InputOwner(output)
        token = owner.press([29], 1)
        with self.assertLogs("maestrod", level="WARNING"):
            self.assertFalse(owner.release(token))
        start = time.monotonic()
        with self.assertLogs("maestrod", level="ERROR") as logs:
            owner.close()
        self.assertLess(time.monotonic() - start, 1)
        self.assertIn("unreleased codes", " ".join(logs.output))
        self.assertTrue(output.closed)
        self.assertFalse(output.held)
        self.assertFalse(owner._thread.is_alive())

    def test_runtime_rejects_single_oversize_delay(self):
        class FakeCancel:
            def __init__(self):
                self.waits = []

            def is_set(self):
                return False

            def wait(self, duration):
                self.waits.append(duration)

        actions = Actions(FakeOutput())
        cancel = FakeCancel()
        with self.assertLogs("maestrod", level="WARNING"):
            actions._run_sequence(
                (0, "delay"),
                {"type": "sequence", "steps": [{"type": "delay", "ms": 6000}]},
                cancel,
            )
        self.assertEqual(cancel.waits, [])

    def test_runtime_caps_survive_mutated_automations(self):
        output = FakeOutput()
        actions = Actions(output)
        actions.automations = {
            "a": {"steps": [{"type": "key", "keys": ["A"]}] * 30},
            "b": {"steps": [{"type": "key", "keys": ["A"]}] * 30},
        }
        with self.assertLogs("maestrod", level="WARNING"):
            actions.execute(
                {
                    "type": "sequence",
                    "steps": [{"type": "automation", "id": "a"}, {"type": "automation", "id": "b"}],
                }
            )
            self.wait_done(actions)
        self.assertEqual(output.events.count(("press", 30)), 50)
        self.assertFalse(output.held)
        actions.automations = {
            ident: {"steps": [{"type": "automation", "id": next_id}]}
            for ident, next_id in (("a", "b"), ("b", "c"), ("c", "d"))
        }
        actions.automations["d"] = {"steps": [{"type": "key", "keys": ["A"]}]}
        with self.assertLogs("maestrod", level="WARNING"):
            actions.execute({"type": "automation", "id": "a"})
            self.wait_done(actions)
        self.assertEqual(output.events.count(("press", 30)), 50)
        actions.automations = {
            "a": {"steps": [{"type": "text", "text": "a" * 300}]},
            "b": {"steps": [{"type": "text", "text": "a" * 300}]},
        }
        with self.assertLogs("maestrod", level="WARNING"):
            actions.execute(
                {
                    "type": "sequence",
                    "steps": [{"type": "automation", "id": "a"}, {"type": "automation", "id": "b"}],
                }
            )
            self.wait_done(actions)
        self.assertEqual(output.events.count(("press", 30)), 350)

        class FastCancel:
            def is_set(self):
                return False

            def wait(self, duration):
                return False

        actions.now = lambda: 0
        with self.assertLogs("maestrod", level="WARNING"):
            actions._run_sequence(
                (0, "test"),
                {"type": "sequence", "steps": [{"type": "delay", "ms": 5000}] * 7},
                FastCancel(),
            )
        actions.now = iter((0, 0, 31)).__next__
        actions.execute(
            {
                "type": "sequence",
                "steps": [{"type": "key", "keys": ["B"]}, {"type": "key", "keys": ["B"]}],
            }
        )
        self.wait_done(actions)
        self.assertEqual(output.events.count(("press", 48)), 1)

    def test_reload_cancels_sequence_without_joining_worker(self):
        entered = threading.Event()

        def slow_run(argv, **kwargs):
            entered.set()
            time.sleep(0.35)
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as directory:
            actions = Actions(FakeOutput(), run=slow_run)
            daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
            daemon.actions = actions
            actions.execute(
                {
                    "type": "sequence",
                    "steps": [{"type": "hyprland", "dispatcher": "workspace", "arg": "e+1"}],
                }
            )
            self.assertTrue(entered.wait(1))
            start = time.perf_counter()
            self.assertTrue(daemon.refresh_config())
            self.assertLess(time.perf_counter() - start, 0.2)
            self.wait_done(actions)
            daemon.close()


class ConfigAPI(unittest.TestCase):
    def test_controls_resolve_model_and_slot_device_overrides(self):
        raw = {
            "settings": {"dpi": 1000},
            "devices": [
                {"match": {"name": "MX Master 2S", "index": 1}, "settings": {"dpi": 800}},
                {"match": {"name": "MX Master 3S", "index": 2}, "settings": {"dpi": 2000}},
                {"match": {"index": 1}, "settings": {"dpi": 800}},
            ],
        }
        first = {"model": "MX Master 2S", "index": 1, "path": "/dev/receiver"}
        second = {"model": "MX Master 3S", "index": 2, "path": "/dev/receiver"}
        self.assertEqual(control_device(first, 0, config=raw)["options"]["settings"]["dpi"], 800)
        self.assertEqual(control_device(second, 1, config=raw)["options"]["settings"]["dpi"], 2000)
        self.assertEqual(
            control_device(first, 0, config=raw)["identity"], {"name": "MX Master 2S", "index": 1}
        )
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            config.apply(raw)
            config.save_device_settings("MX Master 2S", "/dev/receiver", 1, {"dpi": 1600})
            self.assertEqual(config.raw["settings"], {"dpi": 1000})
            self.assertEqual(
                control_device(first, 0, config=config.raw)["options"]["settings"]["dpi"], 1600
            )
            self.assertEqual(
                control_device(second, 1, config=config.raw)["options"]["settings"]["dpi"], 2000
            )

    def test_profile_native_gesture_disables_diversion_without_changing_other_apps(self):
        device = FakeDevice()
        session = MouseSession(device, Actions(FakeOutput()))
        self.addCleanup(session.close)
        raw = {
            "buttons": {"gesture": {"type": "key", "keys": ["CTRL", "C"]}},
            "gesture": {"enabled": False},
            "profiles": [
                {
                    "match": {"class": "firefox"},
                    "buttons": {"gesture": None},
                    "gesture": {"enabled": True},
                }
            ],
        }
        session.configure(resolve(raw, session.identity))
        self.assertIsNone(session.gesture_cid)
        self.assertIn(0xC3, session.bindings)
        session.configure(resolve(raw, session.identity, {"class": "firefox"}))
        self.assertIsNone(session.gesture_cid)
        self.assertNotIn(0xC3, session.diversion.owned)
        self.assertNotIn(0xC3, session.bindings)
        self.assertEqual(device.reporting[0xC3], 0)
        self.assertEqual(raw["buttons"]["gesture"], {"type": "key", "keys": ["CTRL", "C"]})
        session.configure(resolve(raw, session.identity))
        self.assertIn(0xC3, session.bindings)

    def test_controls_battery_on_direct_and_daemon_paths_is_read_only(self):
        cases = [
            (
                mouse.Battery(82, "discharging", False, "0x1000"),
                {"percent": 82, "charging": False, "status": "discharging"},
            ),
            (
                mouse.Battery(0, "discharging", False),
                {"percent": 0, "charging": False, "status": "discharging"},
            ),
            (
                mouse.Battery(67, "charging", True),
                {"percent": 67, "charging": True, "status": "charging"},
            ),
            (None, None),
            (mouse.hidpp.NoResponse("battery read timed out"), None),
        ]
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
            self.addCleanup(daemon.close)
            for value, expected in cases:
                for running in (False, True):
                    with self.subTest(battery=expected, daemon=running):
                        device = FakeDevice()
                        daemon.devices = [device]
                        stdout = io.StringIO()
                        battery_result = (
                            {"side_effect": value}
                            if isinstance(value, Exception)
                            else {"return_value": value}
                        )
                        with (
                            patch("maestro.mouse.battery", **battery_result) as reader,
                            patch("maestro.__main__.mouse.find_mice", return_value=[device]),
                            patch(
                                "maestro.__main__.ipc.request_if_running",
                                side_effect=daemon.handle if running else lambda message: None,
                            ),
                            contextlib.redirect_stdout(stdout),
                        ):
                            self.assertEqual(cli.main(["controls", "--json"]), 0)
                        result = json.loads(stdout.getvalue())
                        self.assertEqual(result["daemon"], running)
                        self.assertEqual(result["devices"][0]["battery"], expected)
                        reader.assert_called_once_with(device)
                        writes = {
                            (mouse.hidpp.REPROG_CONTROLS_V4, 3),
                            (mouse.hidpp.THUMB_WHEEL, 2),
                            (mouse.hidpp.ADJUSTABLE_DPI, 3),
                            (mouse.hidpp.SMART_SHIFT, 1),
                            (mouse.hidpp.HIRES_WHEEL, 2),
                        }
                        self.assertFalse(
                            any(
                                (feature, function) in writes
                                for feature, function, _ in device.calls
                            )
                        )

    def test_offline_undo_backup_failure_preserves_config_and_history(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            name = config.apply({"settings": {"dpi": 1200}})
            before = config.path.read_bytes()
            backups = config.backups()
            original_atomic = config._atomic

            def failed_redo(path, data):
                if path.parent.name == "redo":
                    raise OSError("redo disk failure")
                return original_atomic(path, data)

            with patch.object(config, "_atomic", side_effect=failed_redo):
                with self.assertRaisesRegex(OSError, "redo disk failure"):
                    config.undo()
            self.assertEqual(config.path.read_bytes(), before)
            self.assertEqual(config.raw["settings"]["dpi"], 1200)
            self.assertEqual(config.backups(), backups)
            self.assertTrue((config.backup_dir / f"{name}.json").exists())
            self.assertEqual(list((config.backup_dir / "redo").glob("*.json")), [])

    def test_rapid_backups_keep_newest_and_repeated_undo_walks_back(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            names = [config.apply({"settings": {"dpi": 1000 + index}}) for index in range(120)]
            self.assertEqual(len(set(names)), 120)
            self.assertEqual(config.backups()[0]["name"], names[-1])
            self.assertEqual(len(config.backups()), 20)
            config.undo()
            self.assertEqual(config.raw["settings"]["dpi"], 1118)
            config.undo()
            self.assertEqual(config.raw["settings"]["dpi"], 1117)
            for _ in range(18):
                config.undo()
            self.assertEqual(config.raw["settings"]["dpi"], 1099)
            with self.assertRaisesRegex(ConfigError, "no configuration backup"):
                config.undo()
            next_name = config.apply({"settings": {"dpi": 1300}})
            self.assertGreater(int(next_name[-12:]), int(names[-1][-12:]))

    def test_failed_apply_restores_live_hardware_and_reports_suspension(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            original_set_dpi = mouse.set_dpi

            def lost_ack(target, value):
                if value == 1200:
                    target.dpi = value
                    raise ValueError("lost acknowledgement")
                return original_set_dpi(target, value)

            try:
                with patch("maestro.daemon.service.mouse.set_dpi", side_effect=lost_ack):
                    with self.assertRaisesRegex(ConfigError, "lost acknowledgement"):
                        daemon.handle({"op": "config_apply", "config": {"settings": {"dpi": 1200}}})
                self.assertEqual(device.dpi, 1000)
                self.assertEqual(config.raw, {})
                original_configure = session.configure
                failed = False

                def suspend_once(options, force=False):
                    nonlocal failed
                    if not failed:
                        failed = True
                        session.suspend(reason="lost acknowledgement")
                    else:
                        original_configure(options, force)

                with patch.object(session, "configure", side_effect=suspend_once):
                    with self.assertRaisesRegex(ConfigError, "suspended or unverified"):
                        daemon.handle(
                            {
                                "op": "config_apply",
                                "config": {"buttons": {"back": {"type": "none"}}},
                            }
                        )
                self.assertEqual(config.raw, {})
            finally:
                daemon.close()

    def test_recovered_session_is_snapshotted_before_first_write(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            session.suspend(reason="asleep before apply")
            self.assertFalse(session.online)
            original_set_dpi = mouse.set_dpi
            observed = []
            from maestro.daemon import service

            original_restore = service.restore_hardware

            def capture_restore(snapshots):
                observed.extend(snapshots)
                return original_restore(snapshots)

            def lost_ack(target, value):
                if value == 1200:
                    target.dpi = value
                    raise ValueError("lost acknowledgement")
                return original_set_dpi(target, value)

            try:
                with (
                    patch("maestro.daemon.service.mouse.set_dpi", side_effect=lost_ack),
                    patch("maestro.daemon.service.restore_hardware", side_effect=capture_restore),
                ):
                    with self.assertRaisesRegex(ConfigError, "lost acknowledgement"):
                        daemon.handle({"op": "config_apply", "config": {"settings": {"dpi": 1200}}})
                self.assertEqual(device.dpi, 1000)
                self.assertEqual(observed[0][0], session)
                self.assertEqual(observed[0][1]["dpi"], 1000)
            finally:
                daemon.close()

    def test_apply_blocks_write_when_live_value_cannot_be_snapshotted(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            session.suspend(reason="asleep before apply")
            try:
                with (
                    patch("maestro.daemon.service.mouse.dpi", return_value=None),
                    patch("maestro.daemon.service.mouse.set_dpi") as write,
                ):
                    with self.assertRaisesRegex(ConfigError, "cannot snapshot dpi"):
                        daemon.handle({"op": "config_apply", "config": {"settings": {"dpi": 1200}}})
                    write.assert_not_called()
                self.assertEqual(device.dpi, 1000)
            finally:
                daemon.close()

    def test_failed_undo_keeps_same_history_target_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            target = config.apply({"settings": {"dpi": 1200}})
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            try:
                with patch.object(daemon, "refresh_config", side_effect=[False, True]):
                    with self.assertRaisesRegex(ConfigError, "reload failed"):
                        daemon.handle({"op": "config_undo"})
                self.assertEqual(config.raw["settings"]["dpi"], 1200)
                self.assertEqual(config.backups()[0]["name"], target)
                self.assertTrue((config.backup_dir / f"{target}.json").exists())
                result = daemon.handle({"op": "config_undo"})
                self.assertEqual(result["backup"], target)
                self.assertEqual(config.raw, {})
            finally:
                daemon.close()

    def test_hardware_restoration_still_runs_if_config_rollback_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigFile(Path(directory) / "config.json")
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            real_replace = config.replace
            real_set_dpi = mouse.set_dpi

            def fail_rollback(raw, *, backup=True):
                if raw == {}:
                    raise OSError("fake disk failure")
                return real_replace(raw, backup=backup)

            def fail_write(target, value):
                if value == 1200:
                    target.dpi = value
                    raise ValueError("lost acknowledgement")
                return real_set_dpi(target, value)

            try:
                with (
                    patch.object(config, "replace", side_effect=fail_rollback),
                    patch("maestro.daemon.service.mouse.set_dpi", side_effect=fail_write),
                ):
                    with self.assertRaisesRegex(ConfigError, "config rollback: fake disk failure"):
                        daemon.handle({"op": "config_apply", "config": {"settings": {"dpi": 1200}}})
                self.assertEqual(device.dpi, 1000)
            finally:
                daemon.close()

    def test_maestro_config_home_override_and_empty_undo(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ, {"MAESTRO_CONFIG_HOME": directory, "XDG_CONFIG_HOME": "/ignored"}
            ),
        ):
            config = ConfigFile()
            self.assertEqual(config.path.parent, Path(directory))
            with self.assertRaisesRegex(ConfigError, "no configuration backup"):
                config.undo()

    def test_apply_backups_restore_and_validation_in_temp_xdg(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": directory,
                    "MAESTRO_CONFIG_HOME": str(Path(directory) / "maestro"),
                },
            ),
        ):
            config = ConfigFile()
            self.assertEqual(full_config(config.raw)["version"], 1)
            start = time.perf_counter()
            first = config.apply({"buttons": {"back": {"type": "none"}}})
            self.assertLess(time.perf_counter() - start, 0.2)
            self.assertEqual(config.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(config.backup_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual((config.backup_dir / f"{first}.json").stat().st_mode & 0o777, 0o600)
            before = config.path.read_bytes()
            with self.assertRaises(ConfigError):
                config.apply({"buttons": {"back": {"type": "key", "keys": ["INVALID"]}}})
            self.assertEqual(config.path.read_bytes(), before)
            self.assertEqual(len(config.backups()), 1)
            second = config.apply({"buttons": {"back": {"type": "key", "keys": ["CTRL"]}}})
            self.assertNotEqual(first, second)
            restored = config.restore(second)
            self.assertIn("none", config.path.read_text())
            self.assertTrue(restored)
            latest = config.apply({"settings": {"dpi": 1400}})
            self.assertEqual(config.backups()[0]["name"], latest)
            config.undo()
            self.assertIn("none", config.path.read_text())
            self.assertNotIn("1400", config.path.read_text())
            self.assertRegex(config.backups()[0]["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
            with self.assertRaises(ConfigError):
                config.restore("../../secrets")
            for index in range(22):
                config.apply({"settings": {"dpi": 1000 + index}})
            self.assertEqual(len(config.backups()), 20)

    def test_cli_json_shapes_offline_and_daemon(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": directory,
                    "MAESTRO_CONFIG_HOME": str(Path(directory) / "maestro"),
                },
            ),
        ):

            def invoke(argv, data="", daemon=None):
                stdout = io.StringIO()
                with (
                    patch("sys.stdin", io.StringIO(data)),
                    patch(
                        "maestro.__main__.ipc.request_if_running",
                        side_effect=daemon or (lambda message: None),
                    ),
                    contextlib.redirect_stdout(stdout),
                ):
                    code = cli.main(argv)
                return code, json.loads(stdout.getvalue())

            code, result = invoke(["config", "get"])
            self.assertEqual(code, 0)
            self.assertEqual(result["version"], 1)
            self.assertIn("automations", result)
            code, result = invoke(["config", "apply", "--stdin"], '{"version":1}')
            self.assertEqual((code, result["reloaded"]), (0, False))
            code, result = invoke(
                ["config", "apply", "--stdin"], '{"buttons":{"back":{"type":"text","text":"x"}}}'
            )
            self.assertEqual(code, 1)
            self.assertEqual(result["errors"][0]["path"], "buttons.back.type")
            code, result = invoke(["config", "backups", "--json"])
            self.assertEqual((code, len(result["backups"])), (0, 1))
            code, result = invoke(["config", "undo"])
            self.assertEqual((code, result["reloaded"]), (0, False))
            code, result = invoke(["catalog", "--json"])
            self.assertEqual((code, result["version"]), (0, 1))
            with patch("maestro.__main__.mouse.find_mice", return_value=[]):
                code, result = invoke(["controls", "--json"])
            self.assertEqual((code, result), (0, {"daemon": False, "devices": []}))
            code, result = invoke(["test-action", "--stdin"], '{"type":"key","keys":["A"]}')
            self.assertEqual(code, 1)
            self.assertIn("daemon", result["errors"][0]["message"])

            config = ConfigFile()
            daemon = Daemon(config)
            daemon.actions = Actions(FakeOutput())
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            self.addCleanup(daemon.close)

            def exchange(message):
                return daemon.handle(message)

            code, result = invoke(["controls", "--json"], daemon=exchange)
            self.assertEqual((code, result["daemon"]), (0, True))
            self.assertEqual(result["devices"][0]["buttons"][0]["name"], "gesture")
            code, result = invoke(["config", "apply", "--stdin"], '{"version":1}', daemon=exchange)
            self.assertEqual((code, result["reloaded"]), (0, True))
            code, result = invoke(["config", "undo"], daemon=exchange)
            self.assertEqual((code, result["reloaded"]), (0, True))
            code, result = invoke(
                ["test-action", "--stdin"], '{"type":"key","keys":["A"]}', daemon=exchange
            )
            self.assertEqual((code, result), (0, {"ok": True}))


class IPCMalformedRequests(unittest.TestCase):
    def test_wrong_types_for_every_request_field_do_not_kill_server(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = Daemon(ConfigFile(Path(directory) / "config.json"))
            daemon.actions = Actions(FakeOutput())
            device = FakeDevice()
            session = MouseSession(device, daemon.actions)
            daemon.sessions.append(session)
            daemon.devices.append(device)
            session.configure(resolve({}, session.identity))
            server = Server(daemon.handle, Path(directory) / "maestro.sock")
            try:
                bad = [
                    {"op": []},
                    {"op": "config_apply", "config": []},
                    {"op": "config_restore", "name": []},
                    {"op": "test_action", "action": []},
                    {"op": "test_action", "action": {"type": "hyprland", "dispatcher": []}},
                    {
                        "op": "test_action",
                        "action": {"type": "hyprland", "dispatcher": "workspace", "arg": []},
                    },
                    {"op": "test_action", "action": {"type": "sequence", "steps": {}}},
                    {"op": "set", "settings": []},
                    {"op": "set", "settings": {"dpi": 1000}, "device": []},
                    {"op": "set", "settings": {"dpi": 1000}, "device": 0, "selector": []},
                    {"op": "diagnose", "devices": {}},
                    {"op": "config_get", "extra": []},
                ]

                def exchange(message):
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.settimeout(1)
                        client.connect(str(server.path))
                        client.sendall(json.dumps(message).encode() + b"\n")
                        server.poll()
                        return json.loads(client.recv(65536))

                for message in bad:
                    with self.subTest(message=message):
                        result = exchange(message)
                        self.assertFalse(result["ok"])
                        self.assertTrue(result["error"])
                self.assertTrue(exchange({"op": "config_get"})["ok"])
            finally:
                server.close()
                daemon.close()


if __name__ == "__main__":
    unittest.main()
