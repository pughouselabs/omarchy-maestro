# Changelog

Notable changes are recorded here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning aims to
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.2] - 2026-10-26

### Added
- MX Master 3, 3S and 4 now show a real picture of the mouse (edited from
  CC BY 4.0 photos by Hayden Schiff), with button markers in the main view and
  the thumb close-up.

### Fixed
- Keep queued bar commands when the bar reloads during an update, handing them
  only to a widget that can take them.

## [0.3.1] - 2026-10-25

### Fixed
- Wait quietly while Solaar or logiops runs instead of exiting into a service
  restart loop. The service gives back its buttons, sends nothing to the mouse,
  shows "Paused: Solaar is running" in status, the bar and the settings app,
  and resumes by itself within about 15 seconds of the other app closing.
- Limit the user service to at most five starts in five minutes (the first
  start counts), so a crash can never restart-loop.
- Bound HID++ draining and requests, including discovery and closed streams.
- Explain a button left diverted by a crash or power loss instead of
  restart-looping. Maestro durably records each diversion before making it,
  keyed by a pseudonymous hash of the mouse's unit ID. It never takes a button
  back by itself, since matching flags cannot show who holds it now: when the
  record shows Maestro had the button on this exact mouse, status and the
  settings app say "Maestro may have left the gesture button taken during an
  unexpected shutdown. Choose Release button to fix it."; otherwise they report
  the button as held by another app. Nothing is written to the mouse until you release it.
  Busy buttons are checked again within about 10 seconds.
- Never divert a button whose record cannot be saved; status says so.
- Check which physical mouse answers before every change. Before any write
  (settings, button and thumb-wheel diversion, release, shutdown cleanup) the
  service reads the mouse's unit ID again and writes only if it matches the
  mouse it opened. This happens immediately before each write and each retry,
  after any feature lookup, so nothing else reaches the mouse in between;
  if one check fails or times out, the rest of that change is stopped with
  nothing more written. A same-model mouse paired into the same receiver slot is
  never changed on the old mouse's behalf, and the old mouse keeps its record.
  A mouse whose unit ID cannot be read is read-only: status works, nothing is
  written, and status says "Maestro could not confirm this mouse's identity,
  so it won't change its settings. Reconnect it."
  `maestro dpi`, `smartshift` and `scroll` run without the service check the
  same way and exit with that message, writing nothing. Any write that has no
  identity check in place is refused.
- `maestro status` no longer fails with "daemon request failed: 'receiver'"
  when a mouse disconnects; it lists the mouse as disconnected.
- Reject malformed, oversized, linked or foreign-owned button records.
- Keep the settings app's device list within the response limit with several
  mice by reading each mouse's resolved options separately.
- Recover stalled bar commands with a watchdog and read back interrupted writes.
- Apply one configuration budget to files, backups, saves and service responses;
  bound UI output and keep the last good configuration after oversized edits.
- Show every core-supported MX mouse family in the bar, in the same order as writes.
- Render dynamic tooltips as plain text and report Smart Actions as Started.
- Isolate desktop detection in tests so the suite also runs outside Hyprland.
- Pin CI actions, restrict permissions and bound job duration.

### Added
- `maestro release-buttons [--mouse N]` and a **Release button** action in the
  settings app to free buttons another app or an earlier run left diverted.
  The release acts only on the mouse you chose: it reads the mouse's unit ID
  again first, and if a different mouse (even the same model, paired into the
  same receiver slot) now sits at that position, or the ID cannot be read, it
  is refused before anything is written. A same-model replacement gets a fresh
  session of its own and nothing of the old mouse's.

### Changed
- Choose the device picture per model: the model's own picture first, then
  one with the same body (MX Master 3, 3S and 4 share an MX Master 3S
  folder; pictures for it are not yet included), else the neutral silhouette.
  An MX Master 3S no longer shows the MX Master 2S picture, and MX Anywhere and
  MX Ergo models show the silhouette. A model's own pictures added later
  replace a shared one within a few seconds. Only controls the mouse reports
  get a dot, and Help credits the picture shown.
- Add an MX Vertical picture (main view, dark-theme view, overhead view and a
  thumb-button close-up).
- Use the Pughouse Labs name, repository and `io.github.pughouselabs.maestro` id.
- Split the udev rule: the required `70-maestro.rules` grants hidraw access
  only, and the optional `71-maestro-uinput.rules` grants `/dev/uinput` for the
  service. The Arch package ships the uinput rule inactive.
- Document the id migration (update the code first, and how to roll back),
  required hidraw access, optional build downloads, local Arch checksum
  procedure, and separate noncommercial image licensing.

## [0.3.0] - 2026-10-25

First public release.

### Added
- Settings app with a device view: assign buttons to shortcuts, Omarchy and
  Hyprland actions, typed text or commands, and try an action before keeping it.
- Gesture-button bundles for window navigation, workspaces, media and zoom,
  with per-direction changes.
- Per-application profiles that follow the focused window.
- Thumb-wheel mode and speed, plus DPI, SmartShift and natural scrolling in
  the app.
- Smart Actions: routines of shortcuts, typed text, delays, commands and clicks
  that can be assigned to a button.
- Instant saving with Undo, automatic config backups and restore, and Reset to
  defaults.
- Welcome tour, Help page with keyboard shortcuts and credits, and light and
  dark theme support that follows the Omarchy theme.
- Optional `maestrod` background service that keeps buttons, gestures and
  settings active and restores them after the mouse sleeps or reconnects.
- Support for the wider MX mouse family (MX Master, Anywhere, Vertical and
  Ergo) through runtime feature discovery. Only the MX Master 2S is tested.
- `maestro diagnose` for identifier-free device reports.
- udev rule, systemd user unit, optional Hyprland window rule, desktop entry
  and an Arch PKGBUILD.

### Changed
- The bar panel has an **Open Maestro** button for the settings app.
- The command line and bar widget route requests through the service when it
  is running, so only one program talks to the mouse.

## [0.2.0] - 2026-10-24

### Added
- Omarchy bar widget for battery, DPI presets, SmartShift, and scrolling.

## [0.1.0] - 2026-10-24

### Added
- HID++ device core and command-line settings for the MX Master 2S.
- Status, DPI, SmartShift, and scroll controls.

[Unreleased]: https://github.com/pughouselabs/omarchy-maestro/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/pughouselabs/omarchy-maestro/releases/tag/v0.3.2
[0.3.1]: https://github.com/pughouselabs/omarchy-maestro/releases/tag/v0.3.1
[0.3.0]: https://github.com/pughouselabs/omarchy-maestro/releases/tag/v0.3.0
