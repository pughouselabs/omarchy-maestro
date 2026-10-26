#!/usr/bin/env bash
# Each instance uses the synthetic CLI or an intentionally missing executable.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
fixture="$repo/tests/fixtures/ui/maestro-fake"
export MAESTRO_CLI="$fixture" MAESTRO_UI_TEST=1 MAESTRO_UI_STATE=/tmp/maestro-ui-failure-state.json
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
stop() {
  qs list --all -j | jq -r --arg path "$repo/app/shell.qml" '.[] | select(.config_path==$path) | .pid' 2>/dev/null | xargs -r kill || true
  sleep 0.3
}
current=$(call fixtureStatus 2>/dev/null || true)
if [[ "$current" == '{}' ]]; then echo 'Close the real Maestro app before running fixture checks.' >&2; exit 1; fi
trap stop EXIT
idle() {
  for ((attempt=0; attempt<450; attempt++)); do
    result=$(call fixtureStatus 2>/dev/null || true)
    if jq -e '.busy == false and .applying == false' >/dev/null 2>&1 <<< "$result"; then return; fi
    sleep 0.1
  done
  echo 'Fixture queue did not become idle' >&2; exit 1
}
start() {
  stop
  env MAESTRO_CLI="$fixture" MAESTRO_UI_TEST=1 MAESTRO_UI_STATE=/tmp/maestro-ui-failure-state.json "$@" qs -d -p "$repo/app" >/dev/null 2>&1
  idle
}
start MAESTRO_APPLY_FIXTURE=apply-warning
# Ensure the repeated run changes a value and exercises apply again.
call fixtureCheck restore
idle
call fixtureCheck save
idle
jq -e '.toast | contains("sleeping mouse") and contains("asleep")' >/dev/null <<< "$result"
printf '%s\n' 'PASS: saved-with-warning toast'
start MAESTRO_FIXTURE_FAILURE=catalog
jq -e '.config.version == 1 and (.message | contains("daemon"))' >/dev/null <<< "$result"
printf '%s\n' 'PASS: JSON command error drains queue'
start MAESTRO_FIXTURE_MALFORMED=catalog
jq -e '.config.version == 1 and (.message | contains("unreadable"))' >/dev/null <<< "$result"
printf '%s\n' 'PASS: malformed response drains queue'
start MAESTRO_CONTROLS_FIXTURE=controls-unavailable
jq -e '.devices[0].thumb_wheel.available == false' >/dev/null <<< "$result"
"$repo/tests/fixtures/ui/capture-app.sh" wheel >/dev/null
cp /tmp/maestro-ui-wheel.png /tmp/maestro-ui-unavailable.png
cp /tmp/maestro-ui-wheel-detail.png /tmp/maestro-ui-unavailable-detail.png
printf '%s\n' 'PASS: unavailable thumb wheel'
start MAESTRO_CONTROLS_FIXTURE=controls-read-error
jq -e '.devices[0].dpi.error != null and .devices[0].smartshift == null and .config.version == 1' >/dev/null <<< "$result"
MAESTRO_CAPTURE_SUFFIX=-read-error "$repo/tests/fixtures/ui/capture-app.sh" point >/dev/null
printf '%s\n' 'PASS: partial controls read failure keeps settings available'
start MAESTRO_FIXTURE_OPTIONS_FAILURE=1
jq -e '.config.version == 1 and (.devices | length) > 0 and (.devices[0] | has("options") | not) and .writable == false and (.message | contains("could not be read"))' >/dev/null <<< "$result"
# Restore first so the save below really changes a value.
call fixtureCheck restore
idle
call fixtureCheck save
idle
jq -e '(.toast | contains("Saved") | not) and (.message | contains("could not be read")) and .writable == false' >/dev/null <<< "$result"
printf '%s\n' 'PASS: failed mouse options keep its controls unavailable and never report Saved'
start MAESTRO_CLI=/tmp/maestro-ui-missing-executable
jq -e '.config == {} and (.message | contains("Could not start"))' >/dev/null <<< "$result"
printf '%s\n' 'PASS: failed executable drains queue'
start MAESTRO_FIXTURE_DELAY=controls
jq -e '.config.version == 1 and (.message | contains("too long"))' >/dev/null <<< "$result"
printf '%s\n' 'PASS: stalled command times out and drains queue'
