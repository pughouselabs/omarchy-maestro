"""Exercise actual QML processes offscreen when Quickshell is installed."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
RUNNER = shutil.which("qs")


class QueueTests(unittest.TestCase):
    @unittest.skipUnless(RUNNER, "Quickshell is not installed")
    def test_actual_qml_queues_offscreen(self):
        with tempfile.TemporaryDirectory(prefix=".queue-test-", dir=ROOT) as directory:
            bundle = Path(directory)
            shutil.copytree(
                ROOT / "app", bundle / "app", ignore=shutil.ignore_patterns("assets", "tools")
            )
            shutil.copy2(ROOT / "tests/fixtures/ui/queues/shell.qml", bundle / "shell.qml")
            result = subprocess.run(
                [RUNNER, "--no-duplicate", "-p", str(bundle)],
                capture_output=True,
                text=True,
                timeout=30,
                env={
                    **{
                        key: value
                        for key, value in os.environ.items()
                        if key not in ("DISPLAY", "WAYLAND_DISPLAY")
                    },
                    "QT_QPA_PLATFORM": "offscreen",
                    # A desktop gtk3 theme plugin would open a display even offscreen.
                    "QT_QPA_PLATFORMTHEME": "",
                    "MAESTRO_QUEUE_CLI": str(ROOT / "tests/fixtures/ui/queue-cli"),
                    "MAESTRO_CLI": str(ROOT / "tests/fixtures/ui/queue-cli"),
                    "MAESTRO_UI_TEST": "1",
                },
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: bounded queues", result.stdout + result.stderr)
        self.assertNotIn("Maestro response:", result.stdout + result.stderr)
