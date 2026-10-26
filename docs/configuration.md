# Maestro daemon configuration

`maestrod` keeps mouse settings across power loss, maps buttons and thumb
gestures, and changes thumb-wheel behavior by application on Omarchy/Hyprland.
It uses Python 3.10+ and the standard library. The MX Master 2S over Unifying
is the available test hardware; other MX models and transports need testers.
Short 2S checks confirmed diversion/undiversion and restoration of DPI,
SmartShift, and scroll direction. A physical gesture-button notification was
not captured, so complete gesture operation on the 2S remains unverified.

## Start locally

Configuration files and backups share a 48 KiB budget, measured as UTF-8 JSON
with indentation, escaping, and all built-in defaults included. This leaves
room in the 64 KiB service message for its envelope. Limits are 32 profiles,
16 device rules, 32 Smart Actions, 256 total stored steps, 50 expanded steps
per routine, 500 characters per label, and 128 command arguments of at most
1024 characters each. Existing delay, text and nesting limits still apply.
Reads are bounded before JSON parsing. An oversized edit or backup is rejected;
the service keeps its last good configuration. Move the oversized file aside
and reduce it or restore a smaller backup before saving again.

Keep Solaar and logiops stopped, including their background services. Maestro
checks for them at startup and every five seconds. One process must own HID++.
While either one runs, the service pauses instead of exiting: it gives back
any buttons it diverted, sends nothing to the mouse, reports the reason in
status, the bar and the settings app, and checks again about every 15 seconds.
While the daemon is running, `bin/maestro` and the bar widget use its socket for
settings and status. Their plain text and JSON output keep the same format.
The CLI uses direct HID++ only when neither the daemon socket nor its ownership
lock is active. A timeout or failed request from a running daemon is reported
without opening a competing hidraw connection.

Save a copy of an existing configuration before editing it. To start with the
default gesture behavior and native horizontal scrolling:

```bash
mkdir -p ~/.config/maestro
cp examples/config/default.json ~/.config/maestro/config.json
bin/maestrod --check-config
bin/maestrod
```

The default path is `$XDG_CONFIG_HOME/maestro/config.json`, or
`~/.config/maestro/config.json` when `XDG_CONFIG_HOME` is unset. `--config PATH`
selects another path. A missing file uses the built-in defaults and changes no
DPI, SmartShift, or scroll-direction settings. `--check-config` never opens a
mouse or uinput. Invalid startup configuration prevents diversion.
For isolated settings-app tests, set `MAESTRO_CONFIG_HOME` to a temporary
directory. It uses `$MAESTRO_CONFIG_HOME/config.json`.

Edits reload within the event loop's next poll, normally under a second. An
atomic replacement by an editor is detected too. `SIGHUP` and the IPC `reload`
operation force a reload. An invalid edit keeps the last good configuration
active; the log and IPC status explain the field that failed validation.
Unknown options, duplicate JSON keys, invalid types, and unknown keys are errors.

## uinput access

Keyboard chords, mouse clicks, and wheel actions use `/dev/uinput`. The daemon
refuses to divert controls if it cannot create its virtual input device. This
also protects against buttons being consumed with no way to emit their actions.
Mouse hidraw access is required separately.

The required `packaging/udev/70-maestro.rules` grants the active seat user
access to Logitech hidraw nodes only. The separate, optional
`packaging/udev/71-maestro-uinput.rules` grants `/dev/uinput`, and
`packaging/modules-load/maestro-uinput.conf` loads the `uinput` module at boot.
The uinput rule is:

```udev
KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"
```

If you choose to install the optional files, copy both into `/etc`, load the `uinput`
kernel module, reload udev rules, and trigger the devices, or log out and back
in (the README lists the exact commands). Verify `test -w /dev/uinput` as the
desktop user. Some distributions instead use an `input` group; follow their
local policy. Access to uinput permits input injection into your session.
No udev rule or systemd service is installed by running this checkout.

## Settings and device rules

```json
{
  "version": 1,
  "settings": {
    "dpi": 1200,
    "smartshift": {"mode": "ratchet", "threshold": 20},
    "invert": false
  },
  "devices": [
    {
      "match": {"name": "*MX Master 2S*", "index": 1},
      "settings": {"dpi": 1000}
    }
  ]
}
```

Omit settings you want Maestro to leave alone. DPI must be one of the mouse's
reported choices. SmartShift mode is `ratchet` or `freespin`, with threshold
1-255; 255 means never auto-switch. `invert` changes vertical scrolling only
and preserves the Linux driver's high-resolution mode bits. Unsupported
settings appear in each device's `errors` in status.

Global settings are applied first, then every matching device rule in file
order. Match fields are `name`, `path`, and `index`; string fields accept
case-insensitive shell globs. All fields in a match must agree. Each device
rule can also override `buttons`, `gesture`, and `thumb_wheel`.

The daemon reapplies these settings and temporary diversions after mouse
connection and HID++ wireless reconfiguration notifications. New endpoints
are discovered every five seconds. A ten-second readback also catches resets
when a receiver does not deliver a wake event. Asleep devices retry on wake.
The daemon uses the core's `hidpp.scan_devices()` identity checks. Receiver
pairing kind is read before addressing a paired device; Bluetooth product and
protocol identity are verified by the same core used by the CLI. Only devices
with a supported core model get action sessions. A mouse with `writable=false`
can be read for status but receives no settings or diversion writes. Receiver
kind and product identity are checked again before writes, including cleanup,
so a slot reassigned to a keyboard is not used for the old mouse's commands.
An incomplete scan or pairing-read timeout suspends actions and releases held
virtual input while keeping diversion ownership. Actions resume only after
identity verification and configuration succeed. Confirmed replacements keep
the original mouse's cleanup record until that original can be verified again.
Shutdown retries cleanup for active, suspended, and replaced sessions.

IPC saves a device-specific rule using its model name and receiver slot, not
its changeable `/dev/hidrawN` number. Identical models at the same slot on
different receivers share that rule. Add explicit `path` rules if necessary,
and update those rules when hidraw numbering changes. Stable serial-number
selection is a future core integration.

## Buttons and actions

Supported button names are `gesture`, `back`, `forward`, `middle`, and
`mode_shift`. Each is matched against the controls actually reported by the
mouse. An unavailable control is reported in status. No model-specific feature
indexes are assumed. Only REPROG_CONTROLS_V4 (`0x1B04`) controls advertising
diversion are diverted.

```json
{
  "buttons": {
    "back": {"type": "key", "keys": ["CTRL", "C"]},
    "forward": {"type": "key", "keys": ["CTRL", "V"]},
    "middle": {"type": "mouse", "button": "middle"},
    "mode_shift": {"type": "command", "argv": ["pavucontrol"]}
  }
}
```

| Action | Fields and behavior |
|---|---|
| `key` | `keys`: Linux key names in press order, released in reverse order |
| `mouse` | `button`: `left`, `right`, `middle`, `back`, `forward`, `side`, or `extra` |
| `command` | `argv`: nonempty argument list, launched once on press, without a shell |
| `desktop` | `action`: `app_switcher`, `fullscreen`, `menu`, `apps`, `workspace_previous`, `workspace_next` |
| `none` | Consume the button without emitting input |
| `null` | Leave this button native |
| `hyprland` | `dispatcher` from the allowlist below, plus `arg` where required; Maestro builds the Lua call |
| `sequence` | `steps`: 1-50 actions run in order off the mouse event loop |
| `automation` | `id`: a named sequence from top-level `automations` |

Button keystrokes and mouse buttons remain held until the physical release,
so middle-button drags work. Gesture and thumb-wheel actions emit a complete
tap. Common key aliases are `CTRL`, `ALT`, `SHIFT`, and `SUPER`; `KEY_LEFTCTRL`
also works. Letters refer to Linux physical key codes, not composed text.
Examples include `LEFTBRACE`, `RIGHTBRACE`, `KP4`, `F12`, and `VOLUMEUP`.
Keyboard layouts and customized application shortcuts may need adjustments.
Commands inherit the daemon's session environment and run with its user rights.
At most 16 unfinished action commands are tracked at once.
Text and delay are available inside sequences. Text supports printable ASCII
on a US keyboard layout; other characters fail validation. See
[Automations](automations.md) for examples and limits.

The settings app uses `bin/maestro catalog --json` for suggested actions and
`bin/maestro controls --json` for controls present on each mouse. Use
`bin/maestro config get` to see built-in defaults merged with your file. A
complete JSON configuration can be applied with
`bin/maestro config apply --stdin < config.json`; validation happens before
any write. The old file is saved in `~/.config/maestro/backups/` and the daemon
reloads it when running. `bin/maestro config backups --json` lists the last 20
copies, `bin/maestro config restore NAME` restores one, and
`bin/maestro config undo` restores the copy saved before the most recent apply.
Repeated Undo walks backward through available snapshots. Restore and undo
each back up the current file. When the daemon is
stopped, config commands work directly and report `"reloaded": false`.
If the daemon cannot reload an Undo, the backup remains in the history so the
same Undo can be retried.
`bin/maestro test-action --stdin` needs a running daemon and executes one
action from standard input. These commands return JSON on standard output,
including validation errors with field paths. Backup files use mode 0600 and
the backup directory uses mode 0700.
An apply returns `{"ok":false,"errors":[...]}` when a mouse is suspended or
unverified during reload. Maestro restores the prior config and verified live
DPI, SmartShift, and scroll values before reporting that error.

An explicit `buttons.gesture` mapping, including `null`, overrides the default
gesture handler for that button. Setting `gesture.enabled` to false disables
gestures while leaving the button's native behavior available.

## Thumb-button gestures on Omarchy/Hyprland

Hold the gesture button and move at least 50 raw sensor counts in a direction,
then release. The first direction to cross the threshold wins; a small movement
remains a tap. The threshold is configurable with `gesture.threshold` (1-10000).
Raw XY is diverted only while that button is held. Default actions are:

| Input | Action |
|---|---|
| Tap | Cycle to the next window through Hyprland |
| Left / right | Previous / next workspace |
| Up | Toggle fullscreen for the active window |
| Down | Toggle the Omarchy menu |

Override any of `gesture.tap`, `left`, `right`, `up`, and `down` with an action.
`gesture.button` can select another named control, if it supports raw XY.
The Blender example replaces these actions with numeric-keypad view controls.

Hyprland is detected through `HYPRLAND_INSTANCE_SIGNATURE` and
`XDG_CURRENT_DESKTOP`. Workspace changes, window cycling, and fullscreen use
Lua dispatchers. `menu` and `apps` run `omarchy-menu toggle root` and
`omarchy-menu toggle apps` as argv lists. Explicit key/chord and command actions
remain available for personal mappings.

GNOME, KDE, Sway, and X11 desktop actions and window tracking are **not supported
yet**. `Actions.desktop_handler` and `Windows.backend` are clean extension
points for future backends. The daemon does not guess those desktops' shortcuts.
It refuses to start in those sessions before opening a mouse. Use an
Omarchy/Hyprland session for this release.

On Omarchy's Lua Hyprland, next workspace is sent as one argument:

```bash
hyprctl dispatch 'hl.dsp.focus({workspace="e+1"})'
```

In a Maestro config, use a structured action instead of Lua text:

```json
{"type":"hyprland","dispatcher":"workspace","arg":"e+1"}
```

Allowed dispatchers are `workspace` and `movetoworkspace` (workspace number
1-99 or `e+N`/`e-N`, N from 1-99), `focuswindow` (`class:NAME` or
`address:0xHEX`), and `movefocus` (`l`, `r`, `u`, or `d`). `fullscreen`,
`togglefloating`, `killactive`, and `cyclenext` take no `arg`. The engine
builds the matching `hl.dsp.*` Lua call and passes it as a single argument to
`hyprctl dispatch`. Arbitrary Lua and command execution are not accepted.

`hyprland_dispatch` is `auto` by default. Set `lua` to require Lua dispatch or
`legacy` for stock Hyprland's `hyprctl dispatch workspace e+1` syntax.
Current Omarchy uses `focus({workspace=...})` in its own bindings;
`hl.dsp.workspace` is a table of workspace management functions on this build.

## Thumb wheel

`thumb_wheel.mode` defaults to `horizontal`, leaving native HID horizontal
scrolling untouched. All other modes divert feature `0x2150` temporarily.
The available 2S does not advertise `0x2150`; it keeps native horizontal
scrolling and reports this limit in status if another mode is selected.
Diverted thumb-wheel modes have fake-device coverage and need hardware testing
on a mouse that advertises this feature.

| Mode | Left / right effect |
|---|---|
| `horizontal` | Native horizontal scroll |
| `volume` | Volume down / up |
| `zoom` | Ctrl+vertical wheel |
| `tabs` | Ctrl+PageUp / PageDown |
| `workspaces` | Previous / next workspace |
| `custom` | Actions from `thumb_wheel.left` and `right` |

`step` is the number of raw wheel counts per action, default 120. Fractions
accumulate within a stroke, reversal cancels the remainder, and a new stroke
resets it. Lower values respond faster. Positive HID++ movement uses `right`;
swap custom actions if your preferred direction differs. A single malformed
packet cannot emit more than 32 steps. Mouse wheel inversion is preserved.

## Per-app profiles and examples

Profiles use `match.class` and optional `match.title`, both case-insensitive
glob patterns. All fields must match. The **first matching profile** wins and
overrides buttons, gestures, or the thumb wheel; place specific title matches
above a general application profile. Profiles cannot change global mouse
settings. Profile changes wait for held diverted buttons to be released, so an
application switch cannot strand a virtual key.

Active-window tracking uses Hyprland's socket2 events to wake up a
`hyprctl activewindow -j` query. Polling catches missed events and reconnects the
event socket when necessary. Other desktops report an unsupported backend in
`window_error`; no Sway/X11 commands or GNOME/KDE shortcut approximations run.

The example files are complete configurations, not automatically included:

- `examples/config/default.json`: defaults, with no forced DPI or SmartShift.
- `examples/config/profiles.json`: exactly three profiles: Chromium browser tabs,
  Blender zoom and gesture view controls, and Kdenlive timeline steps. For Firefox,
  replace the browser class pattern with `*firefox*`.

Copy a selected file to your config path, or combine its `profiles` entries.
Shortcuts are examples for standard application keymaps, not claims of testing
those applications. Timeline keys act on the focused editor; numeric keypad
view keys depend on Blender preferences. Inspect IPC `window.class` and
`window.title` to tune patterns for Flatpak, native, browser, and PWA variants.

## IPC for CLI and bar integrations

The daemon listens on `$XDG_RUNTIME_DIR/maestro.sock`, mode `0600`, and checks
the connecting user's credentials. A process lock prevents two daemons from
owning the endpoint. It replaces a stale socket after a crash and refuses to
replace a regular file. The runtime directory must belong to your user and
must not be writable by other users.

Send one UTF-8 JSON object followed by a newline. Read one JSON object followed
by a newline, then close. Requests are at most 65536 bytes; incomplete requests
expire after five seconds. Response fields may be added later. Errors return
`{"ok":false,"error":"explanation"}`.

```json
{"op":"status"}
{"op":"set","device":0,"settings":{"dpi":1200}}
{"op":"set","device":0,"settings":{"smartshift":{"mode":"ratchet","threshold":20}}}
{"op":"set","device":0,"settings":{"invert":true}}
{"op":"reload"}
{"op":"controls"}
{"op":"controls","device":0}
{"op":"release_buttons","device":0}
```

`device` is the zero-based position in status `devices`, default 0; receiver
slot is separately reported as `index`. `status` returns `ok`, `devices`,
`config_error`, `window`, and `window_error`. Each device includes the existing
mouse status fields plus `online`, `profile`, `errors`, `diverted_controls`,
`thumb_diverted` and `release_available` (true while a control is busy), and
`problem` when a control is unavailable. `writable` reports the core's identity-based write
permission. Unsupported Logitech mice can appear for `maestro status --all`
without action sessions. The daemon also includes `sleeping` and `scan_errors`.

```bash
bin/maestrod --request '{"op":"status"}'
bin/maestrod --request '{"op":"set","settings":{"dpi":1200}}'
```

Python clients can use `maestro.daemon.ipc.request(message)`, or
`request_if_running(message)` to distinguish a running owner from a stopped
daemon. The latter returns `None` only when both listener and ownership lock
are inactive. Other socket errors do not permit a direct HID++ fallback.
Successful `set` responses include the mouse's core `status` snapshot. Clients
can include `selector` with `path`, `index`, and `model` to reject a changed
device between selection and the write. `diagnose` requests are also routed
through the owner and accept an optional list of `devices` numbers.

`controls` lists the settings-app view of every supported mouse without
resolved options, so the response stays within the message limit with several
mice. With `device` it returns only that mouse and adds its resolved
`options`, which the configuration budget keeps within the limit
(`maestro controls --mouse N --json` from the command line).

`release_buttons` is the explicit recovery for a button that is busy (see
[troubleshooting](troubleshooting.md)). Without `device` it applies to every
mouse. With `device` it also needs that mouse's `selector`, copied from
`controls` (or built from `status`): `{"path", "index", "model", "unit"}`,
where `unit` is the status field `unit_key`, a short pseudonymous tag of the
mouse's unit ID (null when the mouse reports none; such a mouse is read-only
and nothing is written to it). If a different mouse now
sits at that device number, the request is refused before anything is written. It clears temporary diversion on each control Maestro can divert that
the service does not own, plus the thumb wheel, then lets the service take the
controls over. The response lists `devices` with `device`, `model` and the
plain names in `released`. `maestro release-buttons [--mouse N]` uses it while
the service runs and talks to the mouse directly otherwise; the settings app
passes `--selector JSON` so the release only ever reaches the mouse it shows.

Settings writes validate against the mouse, confirm readback, and save JSON
with an atomic replacement. The previous file is backed up as `config.json.bak`
with mode `0600`. If saving fails, hardware settings are restored to their
previous values. An unread external edit prevents overwriting the config; reload
it first. Config changes from IPC use model and slot matching as described above.
When necessary, IPC appends a narrow final rule so the requested settings win
without changing unrelated settings or button mappings. Success requires the
effective resolved settings and final hardware readback to match the request.
Conflicts name the overriding rule; failed verification restores the previous
configuration and mouse values when the original endpoint can be verified.

## Optional user service

`packaging/systemd/maestrod.service` is a systemd user unit. It starts
`~/.local/bin/maestrod` with your graphical session. `packaging/install.sh` and
pipx put `maestrod` there; for a plugin checkout, link the checkout's
`bin/maestrod` into `~/.local/bin` instead (see the README). Copy the unit into
`~/.config/systemd/user/`, run `systemctl --user daemon-reload`, then
`systemctl --user enable --now maestrod.service`. Use a systemd drop-in if your
`maestrod` lives elsewhere. Import compositor environment variables into the
user manager when your desktop does not do so automatically (Omarchy does). The
unit runs as your desktop user, never root. systemd allows at most five starts
in five minutes (the first start counts), then stops restarting it after a
crash; `journalctl --user -u maestrod` shows why it stopped.

Maestro never installs or enables the service or udev rules by itself. The Arch
package installs the unit and the required hidraw rule but leaves the service
disabled and ships the optional uinput rule inactive (see
[install](install.md)).

## Stop and undo

Ctrl+C, SIGTERM, SIGINT, and exception cleanup release virtual keys and
undivert every control Maestro owns, with readback checks. The thumb wheel
returns to native mode while keeping its direction. Diversions are temporary;
Maestro never enables persistent control diversion. Other mouse settings stay
at your configured values when the daemon exits.

To undo configuration changes, stop the daemon and restore your saved JSON
or `config.json.bak`, then restart. To undo persistent DPI/SmartShift/invert
changes, send their previous values over IPC before stopping, or restore the
original values with the standalone CLI after the daemon has stopped. Disable
and remove the user unit and udev rule if you installed them.

No process can run cleanup after SIGKILL, a kernel failure, or a disconnected
receiver. Maestro records each diversion durably before making it, so the
next start can tell you a button was left taken, but it never takes one back
by itself (see [troubleshooting](troubleshooting.md)). Choose **Release
button** in the settings app, run `maestro release-buttons`, or power-cycle
that mouse to clear temporary diversion. Never leave a hardware experiment
running unattended. Real hardware write checks must snapshot settings, use a
`finally` to restore them, and confirm readback.

## Tests

```bash
python3 -m unittest discover -s tests
```

Daemon tests use fake devices, socket event streams, and a fake uinput fd.
They exercise lost acknowledgements, diversion cleanup, gestures, wheel step
accumulation, profile switching, configuration persistence, IPC, and startup
failure. They do not require a mouse or change the desktop.
