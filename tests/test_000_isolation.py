import os
import unittest
from pathlib import Path

import isolation


class IsolationTests(unittest.TestCase):
    def test_tests_never_see_the_live_service_or_settings(self):
        root = Path(isolation._ROOT)
        for name in ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "MAESTRO_CONFIG_HOME"):
            self.assertTrue(Path(os.environ[name]).is_relative_to(root), name)
        self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", os.environ)
        self.assertEqual(os.environ["XDG_CURRENT_DESKTOP"], "Hyprland")


if __name__ == "__main__":
    unittest.main()
