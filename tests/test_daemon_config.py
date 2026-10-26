import json
import tempfile
import unittest
from pathlib import Path

import isolation  # noqa: F401  (private runtime and config dirs)

from maestro.daemon.config import ConfigError, ConfigFile, validate
from maestro.daemon.profiles import resolve


class ConfigTests(unittest.TestCase):
    def test_good_complete_config(self):
        raw = {
            "version": 1,
            "settings": {
                "dpi": 1200,
                "smartshift": {"mode": "ratchet", "threshold": 16},
                "invert": True,
            },
            "buttons": {
                "back": {"type": "key", "keys": ["CTRL", "C"]},
                "middle": {"type": "mouse", "button": "middle"},
            },
            "gesture": {"threshold": 25},
            "thumb_wheel": {"mode": "tabs", "step": 60},
            "devices": [{"match": {"name": "MX Master*", "index": 1}, "settings": {"dpi": 1000}}],
            "profiles": [
                {"name": "Browser", "match": {"class": "firefox*"}, "thumb_wheel": {"mode": "tabs"}}
            ],
        }
        self.assertEqual(validate(raw), raw)

    def test_invalid_values_have_paths(self):
        cases = [
            ({"settings": {"dpi": True}}, "config.settings.dpi"),
            ({"settings": {"dpi": 0}}, "config.settings.dpi"),
            ({"settings": {"invert": "yes"}}, "config.settings.invert"),
            (
                {"settings": {"smartshift": {"threshold": 256}}},
                "config.settings.smartshift.threshold",
            ),
            ({"gesture": {"threshold": 0}}, "config.gesture.threshold"),
            ({"gesture": {"enabled": 1}}, "config.gesture.enabled"),
            ({"thumb_wheel": {"mode": "custom"}}, "config.thumb_wheel"),
            ({"thumb_wheel": {"step": 0}}, "config.thumb_wheel.step"),
            (
                {"buttons": {"back": {"type": "key", "keys": ["SECRET"]}}},
                "config.buttons.back.keys[0]",
            ),
            (
                {"buttons": {"back": {"type": "key", "keys": ["CTRL", "LEFTCTRL"]}}},
                "config.buttons.back.keys",
            ),
            (
                {"buttons": {"back": {"type": "command", "argv": "sh -c anything"}}},
                "config.buttons.back.argv",
            ),
            (
                {"buttons": {"back": {"type": "command", "argv": ["echo", "x\0y"]}}},
                "config.buttons.back.argv",
            ),
            ({"buttons": {"back": {"type": []}}}, "config.buttons.back.type"),
            ({"buttons": {"back": {"type": "mouse", "button": {}}}}, "config.buttons.back.button"),
            ({"buttons": {"typo": None}}, "config.buttons.typo"),
            ({"profiles": [{"match": {}}]}, "config.profiles[0].match"),
            (
                {"profiles": [{"match": {"class": "*"}, "settings": {"dpi": 1000}}]},
                "config.profiles[0].settings",
            ),
            ({"version": True}, "config.version"),
            ({"typo": True}, "config.typo"),
        ]
        for raw, path in cases:
            with self.subTest(raw=raw), self.assertRaises(ConfigError) as error:
                validate(raw)
            self.assertIn(path, str(error.exception))

    def test_last_good_reload_and_atomic_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            config = ConfigFile(path)
            self.assertEqual(config.raw, {})
            path.write_text('{"settings":{"dpi":1000}}')
            self.assertTrue(config.changed())
            self.assertTrue(config.reload())
            path.write_text('{"settings":{"dpi":false}}')
            self.assertFalse(config.reload())
            self.assertEqual(config.raw["settings"]["dpi"], 1000)
            self.assertFalse(config.changed())
            replacement = path.with_suffix(".tmp")
            replacement.write_text('{"settings":{"dpi":1200}}')
            replacement.replace(path)
            self.assertTrue(config.changed())
            self.assertTrue(config.reload())
            self.assertEqual(config.raw["settings"]["dpi"], 1200)

    def test_duplicate_keys_and_broken_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for text in ('{"settings":{},"settings":{}}', '{"x":', "[]"):
                path.write_text(text)
                self.assertIsNotNone(ConfigFile(path).error)

    def test_save_preserves_other_options_and_backs_up(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            old = {
                "buttons": {"back": {"type": "none"}},
                "devices": [{"match": {"name": "*"}, "settings": {"invert": True}}],
            }
            path.write_text(json.dumps(old))
            config = ConfigFile(path)
            config.save_device_settings("MX Master 2S", "/dev/hidraw13", 1, {"dpi": 1200})
            self.assertEqual(json.loads(path.with_suffix(".json.bak").read_text()), old)
            self.assertEqual(config.raw["buttons"], old["buttons"])
            self.assertEqual(
                resolve(config.raw, {"name": "MX Master 2S", "path": "/dev/hidraw99", "index": 1})[
                    "settings"
                ],
                {"invert": True, "dpi": 1200},
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            config.save_device_settings(
                "MX Master 2S", "/dev/hidraw99", 1, {"smartshift": {"threshold": 20}}
            )
            self.assertEqual(len(config.raw["devices"]), 2)

    def test_save_refuses_overwriting_unread_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{}")
            config = ConfigFile(path)
            path.write_text('{"gesture":{"enabled":false}}')
            with self.assertRaises(ConfigError):
                config.save_device_settings("MX Master 2S", "/dev/fake", 1, {"dpi": 1200})
            self.assertIn("false", path.read_text())

    def test_every_shipped_example_validates(self):
        paths = list((Path(__file__).resolve().parents[1] / "examples/config").glob("*.json"))
        for path in paths:
            with self.subTest(path=path.name):
                self.assertIsNone(ConfigFile(path).error)
        self.assertEqual(sum(len(ConfigFile(p).raw.get("profiles", [])) for p in paths), 3)


class ProfileTests(unittest.TestCase):
    def test_device_then_first_app_match(self):
        raw = validate(
            {
                "buttons": {"back": {"type": "key", "keys": ["ALT", "LEFT"]}},
                "devices": [{"match": {"name": "mx master*"}, "gesture": {"threshold": 100}}],
                "profiles": [
                    {
                        "name": "Figma",
                        "match": {"class": "*chrom*", "title": "*FIGMA*"},
                        "thumb_wheel": {"mode": "zoom"},
                    },
                    {
                        "name": "Browser",
                        "match": {"class": "*chrom*"},
                        "thumb_wheel": {"mode": "tabs"},
                    },
                ],
            }
        )
        result = resolve(
            raw, {"name": "MX Master 2S"}, {"class": "Chromium", "title": "Design - Figma"}
        )
        self.assertEqual(result["profile"], "Figma")
        self.assertEqual(result["thumb_wheel"]["mode"], "zoom")
        self.assertEqual(result["gesture"]["threshold"], 100)
        self.assertIn("back", result["buttons"])
        self.assertEqual(
            resolve(raw, {"name": "MX Master 2S"}, {"class": "chromium", "title": "News"})[
                "profile"
            ],
            "Browser",
        )

    def test_no_window_uses_global_and_does_not_mutate_config(self):
        raw = validate({"profiles": [{"match": {"class": "*"}, "gesture": {"enabled": False}}]})
        result = resolve(raw, {"name": "MX Master 2S"}, {})
        self.assertTrue(result["gesture"]["enabled"])
        result["gesture"]["enabled"] = False
        self.assertTrue(resolve({}, {})["gesture"]["enabled"])
