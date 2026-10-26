#!/usr/bin/env bash
# Run only against an already started, isolated MAESTRO_UI_TEST=1 app.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
idle() {
  for ((attempt=0; attempt<100; attempt++)); do
    result=$(call fixtureStatus 2>/dev/null || true)
    if jq -e '.busy == false and .applying == false and .config.version == 1' >/dev/null 2>&1 <<< "$result"; then return; fi
    sleep 0.1
  done
  echo 'Fixture app did not become idle' >&2; exit 1
}
idle
call fixtureCheck keys
result=$(call fixtureStatus)
jq -e ".keysOK" >/dev/null <<< "$result"
call fixtureCheck restore
idle
call fixtureCheck save
idle
jq -e '.config.buttons.back.keys == ["CTRL","C"] and .undo' >/dev/null <<< "$result"
call fixtureCheck undo
idle
jq -e '.config.buttons.back == null and (.undo | not)' >/dev/null <<< "$result"
call fixtureCheck invalid
idle
jq -e '.errors[0].path == "buttons.back.keys" and .config.buttons.back == null' >/dev/null <<< "$result"
call fixtureCheck test
idle
call fixtureCheck save
idle
jq -e '.config.buttons.back.keys == ["CTRL","C"] and .errors == []' >/dev/null <<< "$result"
call fixtureCheck profile
call fixtureCheck save
idle
jq -e '.config.profiles[0].buttons.back.keys == ["CTRL","C"] and .config.buttons.back.keys == ["CTRL","C"]' >/dev/null <<< "$result"
call fixtureCheck undo
idle
jq -e '.config.profiles[0].buttons.back == null' >/dev/null <<< "$result"
call fixtureCheck reset-profile
call fixtureCheck restore
idle
jq -e '.config.buttons.back == null and .undo' >/dev/null <<< "$result"
printf '%s\n' 'PASS: recorder key names, stdin apply, Undo, rejected change rollback, test action, queue recovery, profile scope, backup restore'
