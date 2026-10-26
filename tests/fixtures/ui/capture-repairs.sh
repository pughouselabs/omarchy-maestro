#!/usr/bin/env bash
# Run on the isolated two-mouse repair app after check-repairs.sh.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
idle() {
  for ((attempt=0; attempt<100; attempt++)); do
    if call fixtureStatus | jq -e '.config.version == 1 and .applying == false and .busy == false' >/dev/null; then return; fi
    sleep 0.1
  done
  exit 1
}
capture() {
  sleep 0.2
  call capture "/tmp/maestro-ui-repair-$1.png"
  for ((attempt=0; attempt<50; attempt++)); do
    if call fixtureStatus | jq -e '.captured' >/dev/null; then return; fi
    sleep 0.1
  done
  echo "Capture did not finish: $1" >&2; exit 1
}
idle
call fixtureRepair device 0
call preview point
capture point-2s
call fixtureRepair device 1
call preview point
capture point-3s
call fixtureRepair device 0
call fixtureRepair gesture-media ''
idle
call preview gestures
capture gestures
for key in altgr keypad backtab unknown; do
  call fixtureRepair "record-$key" ''
  capture "shortcut-$key"
done
call fixtureRepair draft-name ''
call fixtureRepair close ''
idle
capture unsaved
call fixtureRepair keep ''
call preview builder-bottom
capture pending-draft
printf '%s\n' 'PASS: captured selected-mouse settings, gesture preset, shortcut chips/errors, close dialog and retained draft'
