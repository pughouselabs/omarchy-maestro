#!/usr/bin/env bash
# The running app must use maestro-isolated and a populated temporary config.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
idle() {
  for ((attempt=0; attempt<200; attempt++)); do
    result=$(call fixtureStatus 2>/dev/null || true)
    if jq -e '.busy == false and .applying == false and .config.version == 1' >/dev/null 2>&1 <<< "$result"; then return; fi
    sleep 0.1
  done
  echo 'Isolated engine app did not become idle' >&2; exit 1
}
idle
call fixtureCheck save
idle
jq -e '.config.buttons.back.keys == ["CTRL","C"] and .undo and .serviceInactive and .serviceHelp and (.serviceNotice | contains("take effect until"))' >/dev/null <<< "$result"
call fixtureCheck undo
idle
jq -e '.config.buttons.back == null and (.undo | not)' >/dev/null <<< "$result"
call fixtureCheck invalid
idle
jq -e '.errors[0].path == "buttons.back.keys[0]" and .config.buttons.back == null' >/dev/null <<< "$result"
call fixtureCheck test
idle
jq -e '.errors[0].message | contains("requires the running")' >/dev/null <<< "$result"
call fixtureCheck save
idle
jq -e '.errors == [] and .config.buttons.back.keys == ["CTRL","C"]' >/dev/null <<< "$result"
call fixtureCheck undo
idle
call fixtureCheck new-smart
idle
jq -e '.config.automations["test-routine"].description == "Test routine" and .errors == []' >/dev/null <<< "$result"
call fixtureCheck undo
idle
jq -e '.config.automations | has("test-routine") | not' >/dev/null <<< "$result"
call fixtureCheck backups
idle
call fixtureCheck restore-latest
idle
jq -e '.undo and (.toast | contains("Backup restored")) and .errors == []' >/dev/null <<< "$result"
call fixtureCheck undo
idle
jq -e '.config.automations["paste-and-send"].name == "Paste and send"' >/dev/null <<< "$result"
printf '%s\n' 'PASS: real engine app apply, Undo, field errors, safe Try it failure, queue recovery, Smart Action creation, backups and restore'
