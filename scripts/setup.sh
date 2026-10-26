#!/usr/bin/env bash
# Contributor environment check for Maestro: scripts/setup.sh
# Read-only: checks Python, runs the unit tests and reports mouse access.
# It never sends anything to a mouse and installs nothing.
set -u
cd "$(dirname "$0")/.."

warn=0
say() { printf '%s\n' "$*"; }

# Python 3.10+, standard library only, so there is nothing to install.
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  say "FAIL  Python 3.10+ is required (found: $(python3 --version 2>&1))"
  exit 1
fi
say "ok    $(python3 --version)"

log=$(mktemp)
if python3 -m unittest discover -s tests -q >"$log" 2>&1; then
  say "ok    unit tests ($(grep -o 'Ran [0-9]* tests*' "$log"))"
else
  say "WARN  unit tests fail on this checkout:"
  sed 's/^/      /' "$log" | tail -20
  warn=1
fi
rm -f "$log"

# Logitech HID nodes (vendor 046D) and whether this user can open them.
found=0
for dev in /sys/class/hidraw/hidraw*; do
  [ -e "$dev/device/uevent" ] || continue
  grep -qi '^HID_ID=.*:0000046D:' "$dev/device/uevent" || continue
  found=1
  node=/dev/$(basename "$dev")
  name=$(sed -n 's/^HID_NAME=//p' "$dev/device/uevent")
  if [ -r "$node" ] && [ -w "$node" ]; then access="read/write"; else access="NO ACCESS"; warn=1; fi
  say "info  $node  $name  ($access)"
done
[ "$found" = 1 ] || say "info  no Logitech HID device connected (unit tests do not need one)"

# One HID++ owner at a time.
for p in solaar logid; do
  if pgrep -x "$p" >/dev/null; then
    say "WARN  $p is running; stop it before any hardware test"
    warn=1
  fi
done

[ "$warn" = 0 ] && say "Setup OK." || say "Setup finished with warnings (see above)."
exit 0
