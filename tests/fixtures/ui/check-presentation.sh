#!/usr/bin/env bash
# Use controls-unavailable and apply-offline with the isolated fixture CLI.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
idle() {
  for ((attempt=0; attempt<100; attempt++)); do
    result=$(call fixtureStatus 2>/dev/null || true)
    if jq -e '.config.version == 1 and .busy == false and .applying == false' >/dev/null 2>&1 <<< "$result"; then return; fi
    sleep 0.1
  done
  echo 'Fixture app did not become idle' >&2; exit 1
}
idle
jq -e '.battery == "82 %" and .builtInWheel and .wheelAssignment == "Horizontal scroll" and .serviceInactive and .serviceHelp' >/dev/null <<< "$result"
call fixtureCheck restore
idle
call fixtureCheck save
idle
jq -e '.toast == "Saved" and .serviceInactive and (.serviceNotice | contains("take effect until"))' >/dev/null <<< "$result"
# The banner remains after the transient saved message disappears.
sleep 6
result=$(call fixtureStatus)
jq -e '.toast == "" and .serviceInactive and .serviceHelp' >/dev/null <<< "$result"
printf '%s\n' 'PASS: battery label, built-in wheel summary, startup-help availability, persistent saved-but-inactive banner'
