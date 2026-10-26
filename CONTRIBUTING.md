# Contributing

Maestro is an early-stage Omarchy plugin for Logitech MX mice. The MX Master 2S
with a Unifying receiver is the only hardware currently tested.

## Development setup

Use Python 3.10 or newer. The runtime has no third-party Python dependencies.
Clone the repository anywhere and link it into the Omarchy plugins folder to
try the widget:

```sh
ln -s "$PWD" ~/.config/omarchy/plugins/io.github.nodrej.maestro
omarchy-shell shell rescanPlugins
omarchy plugin enable io.github.nodrej.maestro
```

`scripts/setup.sh` checks Python, runs the unit tests and lists Logitech hidraw
nodes and their access. It is read-only and never talks to a mouse.

```sh
python3 -m unittest discover -s tests
ruff check .
ruff format --check .
/usr/lib/qt6/bin/qmllint -i app/qmldir -I /usr/lib/qt6/qml app/*.qml app/interaction/*.qml
```

Do not test with a live Solaar daemon or logiops process; only one program
should own the HID++ link. The unit tests use fake devices and a private
runtime directory, so they never touch a running `maestrod` or your settings.

## Working on the settings app

The UI checks run against a fixture engine and never use your real config,
service or mouse. Every UI probe sources `tests/fixtures/ui/isolation.sh`, which
points all XDG directories at private `/tmp/maestro-ui-*` trees. The fixture
engine and check scripts need `jq`, a development-only tool.

Open the app with fixture data:

```bash
(
  source tests/fixtures/ui/isolation.sh
  MAESTRO_CLI="$PWD/tests/fixtures/ui/maestro-fake" \
  MAESTRO_UI_STATE=/tmp/maestro-ui-demo.json MAESTRO_UI_TEST=1 \
    bin/maestro-settings > "$XDG_STATE_HOME/maestro/preview.log" 2>&1 &
  maestro_preview_pid=$!
  trap 'kill "$maestro_preview_pid" 2>/dev/null || true' EXIT
  tests/fixtures/ui/check-app.sh
  tests/fixtures/ui/capture-app.sh home buttons smart
)
```

The app's preview and test IPC methods only answer when both fixture
environment variables are set. Close the fixture app and relaunch without them
to return to real settings.

Design and behavior checks:

```bash
app/tools/check-design.sh
bash tests/fixtures/ui/check-polish.sh
MAESTRO_THEME_PATH=/usr/share/omarchy/themes/catppuccin-latte app/tools/check-design.sh
tests/fixtures/ui/check-repairs.sh
tests/fixtures/ui/check-launchers.sh
tests/fixtures/ui/check-qml.sh
```

`tests/fixtures/ui/check-engine.sh` exercises the real engine with a fresh
`/tmp/maestro-ui-*` directory for both config and the daemon socket. It never
starts a daemon or changes mouse settings. Keep the private socket override as
well as the config override: a config directory alone does not isolate a
running daemon.

### Screenshots

Recreate the screenshots in `docs/screenshots` with the fixture engine:

```bash
MAESTRO_CAPTURE_WIDTH=1600 MAESTRO_CAPTURE_HEIGHT=1000 \
  app/tools/capture-preview.sh home buttons gestures smart
```

Exports go to `/tmp/maestro-ui-*.png`, with review copies named
`/tmp/maestro-ui-review-<screen>-<theme>-<size>.png`. Use
`MAESTRO_CAPTURE_THEME=catppuccin-latte` for a named theme, or
`MAESTRO_THEME_PATH=/path/to/theme` to preview a theme without changing your
desktop. `preview.png` at the repository root is the marketplace preview and
matches `docs/screenshots/device.png`.

The checks confirm 4.5:1 contrast for text and 3:1 for control boundaries in
the installed Omarchy themes. That is a color-contrast check, not a full
accessibility audit.

### Device images

See [app/assets/devices/README.md](app/assets/devices/README.md) for the image
and hotspot format. `tools/render-device.py` renders transparent device images
from a glTF model in Blender. Every image needs a source and license credit.

## Adding a device

Start with a sanitized `maestro diagnose` report from a supported MX mouse.
Reports redact serial numbers; review the output before sharing it. Identify
the product and transport, then check the HID++ feature and model behavior
against reliable documentation and tester evidence. Add behavior based on
runtime feature discovery where possible, with tests for devices or reports
that can be exercised without hardware. Clearly label untested model support.

## Hardware changes

For any hardware write test, capture the original setting first. Restore it in
a `finally` block and read it back afterward to confirm restoration. Never
send HID++ commands to keyboards or non-MX devices. Do not run tests while
Solaar or logiops owns the device.

## Changes

Keep user-facing documentation in US English. Include the exact reproduction
steps for bugs and avoid publishing device identifiers or serial numbers.
