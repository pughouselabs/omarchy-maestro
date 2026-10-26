"""Keep every test away from the user's live Maestro service, settings and desktop.

Imported by each test module. Points the runtime, config and state folders at a
private temporary directory, so a running maestrod (its socket lives in
XDG_RUNTIME_DIR) or a real ~/.config/maestro can never be reached by a test.
"""

import atexit
import os
import shutil
import tempfile

_ROOT = tempfile.mkdtemp(prefix="maestro-tests-")
atexit.register(shutil.rmtree, _ROOT, True)

for _name in ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME"):
    _path = os.path.join(_ROOT, _name.lower())
    os.makedirs(_path, mode=0o700, exist_ok=True)
    os.environ[_name] = _path
os.environ["MAESTRO_CONFIG_HOME"] = os.path.join(_ROOT, "xdg_config_home", "maestro")
os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
