"""Fixture shell entrypoints must not inherit personal XDG paths."""

import json
import os
import subprocess
import unittest
from pathlib import Path

import isolation  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/ui"


class UiIsolationTests(unittest.TestCase):
    def test_helper_replaces_all_personal_xdg_paths(self):
        env = dict(os.environ)
        for name in (
            "XDG_RUNTIME_DIR",
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
        ):
            env[name] = "/not-a-private-test-path"
        query = (
            "import json, os; print(json.dumps({k:v for k,v in os.environ.items() "
            'if k.startswith("XDG_") or k == "MAESTRO_CONFIG_HOME"}))'
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; python3 -c "$2"',
                "fixture-test",
                str(FIXTURES / "isolation.sh"),
                query,
            ],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        values = json.loads(result.stdout)
        for name in (
            "XDG_RUNTIME_DIR",
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
        ):
            self.assertTrue(values[name].startswith("/tmp/maestro-ui-"), (name, values[name]))
            self.assertTrue(Path(values[name]).is_dir())
        self.assertTrue(values["MAESTRO_CONFIG_HOME"].startswith(values["XDG_CONFIG_HOME"]))

    def test_every_ui_shell_script_sources_isolation(self):
        for path in FIXTURES.glob("*.sh"):
            if path.name != "isolation.sh":
                self.assertIn('source "$repo/tests/fixtures/ui/isolation.sh"', path.read_text())
        wrapper = (FIXTURES / "maestro-isolated").read_text()
        for name in (
            "XDG_RUNTIME_DIR",
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
            "XDG_DATA_HOME",
            "XDG_CACHE_HOME",
        ):
            self.assertIn(name + "=", wrapper)
