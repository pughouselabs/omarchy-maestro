"""Device pictures are chosen per model and every picture folder carries its credits."""

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

import isolation  # noqa: F401  (private runtime and config dirs)

ROOT = Path(__file__).resolve().parents[1]
DEVICES = ROOT / "app" / "assets" / "devices"
ASSETS_JS = ROOT / "app" / "DeviceAssets.js"
QML_TEST = ROOT / "tests" / "fixtures" / "ui" / "qml" / "tst_deviceassets.qml"
RUNNER = Path("/usr/lib/qt6/bin/qmltestrunner")

# The owner's mapping: models that share a body share a render; nothing else does.
SAME_BODY = {
    "MX Master": "mx-master",
    "MX Master 2S": "mx-master",
    "MX Master 3": "mx-master-3s",
    "MX Master 3S": "mx-master-3s",
    "MX Master 4": "mx-master-3s",
    "MX Vertical": "mx-vertical",
}


def has_picture(folder):
    return (folder / "hero.png").is_file() or (folder / "top.png").is_file()


class DeviceAssetTests(unittest.TestCase):
    def test_same_body_map_matches_the_supported_models(self):
        source = ASSETS_JS.read_text()
        block = re.search(r"const SAME_BODY = \{(.*?)\}", source, re.S).group(1)
        found = dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', block))
        self.assertEqual(found, SAME_BODY)
        from maestro import devices

        models = {name for _, name in devices._MODELS} | set(devices.KNOWN_PRODUCTS.values())
        # Every mapped name is a real model, and Anywhere and Ergo models never
        # borrow another model's picture.
        self.assertLessEqual(set(found), models)
        self.assertTrue(any(m.startswith(("MX Anywhere", "MX Ergo")) for m in models))
        for model in models:
            if model.startswith(("MX Anywhere", "MX Ergo")):
                self.assertNotIn(model, found)

    def test_every_picture_folder_has_credits_and_a_license(self):
        self.assertTrue(has_picture(DEVICES / "mx-master"))
        for folder in sorted(p for p in DEVICES.iterdir() if p.is_dir()):
            if not has_picture(folder):
                continue  # no picture yet: the app falls back as documented
            with self.subTest(folder=folder.name):
                self.assertTrue((folder / "LICENSE.txt").is_file())
                metadata = json.loads((folder / "hotspots.json").read_text())
                for key in ("credit", "credit_url", "license", "license_url"):
                    self.assertIsInstance(metadata.get(key), str)
                    self.assertTrue(metadata[key].strip(), key)
                hotspots = metadata.get("hotspots", [])
                names = (
                    set(hotspots)
                    if isinstance(hotspots, dict)
                    else {point["name"] for point in hotspots}
                )
                self.assertLessEqual(
                    names,
                    {
                        "middle",
                        "mode_shift",
                        "wheel_mode",
                        "thumb_wheel",
                        "forward",
                        "back",
                        "gesture",
                    },
                )

    def test_missing_model_folders_are_allowed(self):
        # mx-master-3s and mx-vertical may not exist yet; the mapping must not
        # depend on them, and their absence falls back to the silhouette.
        for folder in set(SAME_BODY.values()) - {"mx-master"}:
            path = DEVICES / folder
            if not path.exists():
                continue
            self.assertTrue(path.is_dir())
        self.assertTrue((DEVICES / "silhouette.png").is_file())

    @unittest.skipUnless(RUNNER.exists(), "qmltestrunner is not installed")
    def test_lookup_rules_in_qml(self):
        result = subprocess.run(
            [str(RUNNER), "-platform", "offscreen", "-input", str(QML_TEST)],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key not in ("DISPLAY", "WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE")
                },
                "QT_QPA_PLATFORM": "offscreen",
                "QT_QPA_PLATFORMTHEME": "",
            },
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertRegex(output, r"Totals: \d+ passed, 0 failed")


if __name__ == "__main__":
    unittest.main()
