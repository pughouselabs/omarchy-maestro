#!/usr/bin/env bash
# New presentation behaviors against fixtures and a private runtime/state tree.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
probe=$(mktemp -d /tmp/maestro-ui-design-check-XXXXXX)
export XDG_STATE_HOME="$probe/state" XDG_RUNTIME_DIR="$probe/runtime" XDG_CONFIG_HOME="$probe/config"
mkdir -m 700 -p "$XDG_STATE_HOME/maestro" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME"
export MAESTRO_CLI="$repo/app/tools/maestro-preview" MAESTRO_UI_STATE="$probe-config.json" MAESTRO_UI_TEST=1 QT_QPA_PLATFORM=offscreen
export MAESTRO_THEME_PATH=${MAESTRO_THEME_PATH:-/usr/share/omarchy/themes/tokyo-night}
jq 'del(.buttons.gesture)' "$repo/tests/fixtures/ui/config.json" > "$MAESTRO_UI_STATE"
app_pid=''
stop() { if [[ -n "$app_pid" ]]; then kill "$app_pid" 2>/dev/null || true; wait "$app_pid" 2>/dev/null || true; app_pid=''; fi; }
trap stop EXIT
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
idle() {
  for ((attempt=0;attempt<120;attempt++)); do
    result=$(call fixtureStatus 2>/dev/null || true)
    if jq -e '.config.version == 1 and .busy == false and .applying == false and .design.welcomeReady' >/dev/null 2>&1 <<< "$result"; then return; fi
    sleep 0.1
  done
  echo 'Design probe did not become idle' >&2; exit 1
}
start() { env -u WAYLAND_DISPLAY -u DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE qs --no-duplicate -p "$repo/app" >> "$probe/app.log" 2>&1 & app_pid=$!; idle; }
start
if ! jq -e '.design.welcomeVisible and .design.welcomeStep == 0 and (.design.contrast | all(. >= 4.5))' >/dev/null <<< "$result"; then jq '.design' <<< "$result" >&2; exit 1; fi
call fixtureRepair welcome-finish ''
jq -e '.completed == true and .version == 1' "$XDG_STATE_HOME/maestro/welcome.json" >/dev/null
stop
start
jq -e '.design.welcomeVisible == false and .design.welcomeCompleted' >/dev/null <<< "$result"
call preview welcome
idle
jq -e '.design.welcomeVisible' >/dev/null <<< "$result"
call fixtureRepair welcome-finish ''
printf '%s\n' 'PASS: first-run welcome, persistent skip/completion, Help reopening'
for category in Productivity Media Screenshots Windows; do
  call fixtureRepair template-category "$category"
  idle
  jq -e '.design.templateCount == 1' >/dev/null <<< "$result"
done
call fixtureRepair template-category Unavailable
idle
jq -e '.design.templateCount == 0' >/dev/null <<< "$result"
call fixtureRepair template-category All
idle
jq -e '.design.templateCount == 4' >/dev/null <<< "$result"
call fixtureRepair try-routine ''
idle
jq -e '.design.trySucceeded' >/dev/null <<< "$result"
printf '%s\n' 'PASS: four template categories and inline Try it success'
baseline=$(jq -c '.config' <<< "$result")
call fixtureRepair restore-defaults ''
idle
jq -e '.config.settings == {} and .config.buttons == {} and .config.profiles == [] and .config.devices == [] and .config.gesture.enabled and .config.automations["paste-and-send"].name == "Paste and send" and .undo' >/dev/null <<< "$result"
call fixtureCheck undo
idle
jq -e --argjson baseline "$baseline" '.config == $baseline' >/dev/null <<< "$result"
printf '%s\n' 'PASS: Restore all defaults keeps Smart Actions; Undo restores the exact config'
jq -e '(.design.contrast | all(. >= 4.5))' >/dev/null <<< "$result"
printf 'PASS: %s contrast ratios (foreground/muted/accent/primary): ' "$(basename "$MAESTRO_THEME_PATH")"
jq -c '.design.contrast' <<< "$result"
if rg 'TypeError|ReferenceError|Binding loop|Failed to load|Cannot assign|Cannot open|Error:' "$probe/app.log"; then exit 1; fi

stop
export MAESTRO_PREVIEW_TWO_MICE=1 MAESTRO_CONTROLS_FIXTURE=controls-two-mice
start
call fixtureRepair device 1
idle
jq -e '(.devices[1].model | test("Anywhere")) and (.design.credit | test("danish_blends")) and (.design.credit | test("No device image") | not)' >/dev/null <<< "$result" || { jq '{devices:[.devices[].model],credit:.design.credit}' <<< "$result" >&2; exit 1; }
unset MAESTRO_PREVIEW_TWO_MICE MAESTRO_CONTROLS_FIXTURE
printf '%s\n' 'PASS: a model without its own picture credits the silhouette source in Help'

# First run must work without a connected device, and skipping is distinct from completion.
stop
rm "$XDG_STATE_HOME/maestro/welcome.json"
export MAESTRO_CLI="$repo/tests/fixtures/ui/maestro-fake" MAESTRO_CONTROLS_FIXTURE=controls-empty
start
jq -e '.devices == [] and .design.welcomeVisible and .design.welcomeCompleted == false' >/dev/null <<< "$result"
call fixtureRepair welcome-skip ''
jq -e '.skipped and .completed == false' "$XDG_STATE_HOME/maestro/welcome.json" >/dev/null
stop
start
jq -e '.design.welcomeVisible == false and .design.welcomeSkipped and .design.welcomeCompleted == false' >/dev/null <<< "$result"
call preview welcome
idle
jq -e '.design.welcomeVisible' >/dev/null <<< "$result"
printf '%s\n' 'PASS: no-mouse first run, distinct skipped state, reopening after skip, empty template category'
