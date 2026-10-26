# Changelog

Notable changes are recorded here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning aims to
follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/nodrej/omarchy-maestro/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nodrej/omarchy-maestro/releases/tag/v0.3.0
