#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
state=/tmp/maestro-ui-repair-state.json
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
stop() {
  qs list --all -j | jq -r --arg path "$repo/app/shell.qml" '.[] | select(.config_path==$path) | .pid' 2>/dev/null | xargs -r kill || true
  sleep 0.15
}
current=$(call fixtureStatus 2>/dev/null || true)
if [[ "$current" == '{}' ]]; then echo 'Close the regular Maestro app before the repair checks.' >&2; exit 1; fi
trap stop EXIT
idle() {
  for ((attempt=0; attempt<150; attempt++)); do
    result=$(call fixtureStatus 2>/dev/null || true)
    if jq -e '.config.version == 1 and .busy == false and .applying == false' >/dev/null 2>&1 <<< "$result"; then return; fi
    sleep 0.1
  done
  echo 'Repair app did not become idle' >&2; exit 1
}
start() {
  stop
  env -u WAYLAND_DISPLAY -u DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE QT_QPA_PLATFORM=offscreen \
    MAESTRO_CLI="$repo/tests/fixtures/ui/maestro-fake" MAESTRO_CONTROLS_FIXTURE=controls-two-mice \
    MAESTRO_CONFIG_FIXTURE=config-two-mice MAESTRO_UI_STATE="$state" MAESTRO_UI_TEST=1 qs -d -p "$repo/app" >/dev/null 2>&1
  idle
}
gone() {
  for ((attempt=0; attempt<100; attempt++)); do
    if ! qs list --all -j | jq -e --arg path "$repo/app/shell.qml" 'any(.[]; .config_path==$path)' >/dev/null 2>&1; then return; fi
    sleep 0.1
  done
  echo 'Close did not finish' >&2; exit 1
}
engine_probe() {
  python3 - "$repo" "$state" "$1" <<'PY'
import json, sys
from pathlib import Path
repo, state, gestures = sys.argv[1:]
sys.path[:0] = [repo, str(Path(repo) / 'tests')]
from daemon_fakes import FakeDevice, FakeOutput
from maestro import mouse
from maestro.daemon.actions import Actions
from maestro.daemon.config import validate
from maestro.daemon.profiles import resolve
from maestro.daemon.service import MouseSession
raw = validate(json.loads(Path(state).read_text()))
sessions = []
try:
    for name, slot, dpi in [('MX Master 2S', 1, 1600), ('MX Master 3S', 2, 2400)]:
        device = FakeDevice(name); device.index = slot
        session = MouseSession(device, Actions(FakeOutput())); sessions.append(session)
        session.configure(resolve(raw, session.identity))
        assert device.dpi == dpi, (name, device.dpi)
        assert mouse.wheel(device).inverted == (slot == 1)
        assert device.smartshift[1] == (32 if slot == 1 else 16)
        assert (session.gesture_cid is not None) == (gestures == 'on')
finally:
    for session in sessions: session.close()
print('PASS: engine fake devices confirm isolated DPI and gestures ' + gestures)
PY
}
rm -f "$state" "$state.undo"
start
jq -e '.selectedDpi == 800 and .devices[1].options.settings.dpi == 2000' >/dev/null <<< "$result"
call fixtureRepair dpi 1600
idle
jq -e '.selectedDpi == 1600 and .devices[1].options.settings.dpi == 2000 and .config.settings.dpi == 1000 and .config.devices[-1].match == {name:"MX Master 2S",index:1}' >/dev/null <<< "$result"
call fixtureRepair invert true
idle
call fixtureRepair smartshift '{"mode":"ratchet","threshold":32}'
idle
call fixtureRepair wheel-mode volume
idle
jq -e '.devices[0].options.thumb_wheel.mode == "volume" and .devices[1].options.thumb_wheel.mode == "horizontal" and .config.thumb_wheel.mode == "horizontal"' >/dev/null <<< "$result"
jq -e '.devices[0].options.settings.invert and .devices[0].options.settings.smartshift.threshold == 32 and .devices[1].options.settings.invert == false and .devices[1].options.settings.smartshift.threshold == 16 and .config.settings.invert == false and .config.settings.smartshift.threshold == 16' >/dev/null <<< "$result"
call fixtureRepair device 1
call fixtureRepair dpi 2400
idle
jq -e '.selectedDpi == 2400 and .devices[0].options.settings.dpi == 1600 and .config.settings.dpi == 1000' >/dev/null <<< "$result"
call fixtureRepair device 0
call fixtureRepair gesture-single ''
idle
jq -e '.config.gesture.enabled == false and .config.buttons.gesture.keys == ["CTRL","C"]' >/dev/null <<< "$result"
engine_probe off
call fixtureCheck profile
call fixtureRepair gesture-media ''
idle
jq -e '.config.buttons.gesture.keys == ["CTRL","C"] and (.config.profiles[0] | has("gesture") | not) and (.message | contains("All applications first"))' >/dev/null <<< "$result"
call fixtureCheck reset-profile
call fixtureRepair gesture-media ''
idle
jq -e '.config.gesture.enabled and (.config.buttons | has("gesture") | not) and .devices[0].options.gesture.tap.keys == ["PLAYPAUSE"]' >/dev/null <<< "$result"
engine_probe on
call fixtureRepair gesture-single ''
idle
engine_probe off
call fixtureRepair gesture-native ''
idle
jq -e '(.config.buttons | has("gesture")) and .config.buttons.gesture == null and .devices[0].options.buttons.gesture == null' >/dev/null <<< "$result"
engine_probe off
call fixtureRepair gesture-media ''
idle
jq -e '.config.gesture.enabled and (.config.buttons | has("gesture") | not)' >/dev/null <<< "$result"
engine_probe on
# App presets delete the local mapping too; null stays reserved for native.
call fixtureCheck profile
call fixtureRepair gesture-single ''
idle
call fixtureRepair gesture-media ''
idle
jq -e '.config.profiles[0].gesture.enabled and (.config.profiles[0].buttons | has("gesture") | not)' >/dev/null <<< "$result"
call fixtureRepair gesture-native ''
idle
jq -e '.config.profiles[0].buttons.gesture == null and .config.profiles[0].gesture.enabled == false' >/dev/null <<< "$result"
call fixtureCheck reset-profile
printf '%s\n' 'PASS: selected mouse DPI readback, unchanged other mouse/global values, gesture and single-action transitions'
call fixtureRepair record-altgr ''
jq -e '.recordedKeys == ["RIGHTALT","Q"]' >/dev/null <<< "$(call fixtureStatus)"
call fixtureRepair record-keypad ''
jq -e '.recordedKeys == ["KP4"]' >/dev/null <<< "$(call fixtureStatus)"
call fixtureRepair record-backtab ''
jq -e '.recordedKeys == ["SHIFT","TAB"]' >/dev/null <<< "$(call fixtureStatus)"
call fixtureRepair record-unknown ''
jq -e --arg message "That key can't be recorded" '.recordedKeys == [] and .recordingMessage == $message' >/dev/null <<< "$(call fixtureStatus)"
printf '%s\n' 'PASS: visible recorder preserves AltGr, keypad and Backtab; unsupported key is rejected'
call fixtureRepair draft-name 'Saved on close'
call fixtureRepair draft-description 'Description saved on close'
call fixtureRepair draft-delay 375
call fixtureRepair draft-text 'Text saved on close'
call fixtureRepair close '' || true
gone
jq -e '.automations["paste-and-send"] | .name == "Saved on close" and .description == "Description saved on close" and .steps[1].ms == 375 and .steps[3].text == "Text saved on close"' "$state" >/dev/null
printf '%s\n' 'PASS: closing commits pending name, description, delay and text edits before exit'
start
call fixtureRepair draft-name ''
call fixtureRepair wm-close ''
idle
jq -e '.closeDialog and .pendingSmart and .smartDrafts["paste-and-send"].name == ""' >/dev/null <<< "$result"
call fixtureRepair close ''
idle
jq -e '.closeDialog and .pendingSmart' >/dev/null <<< "$result"
jq -e '.automations["paste-and-send"].name == "Saved on close"' "$state" >/dev/null
call fixtureRepair keep ''
jq -e '.pendingSmart and (.closeDialog | not)' >/dev/null <<< "$(call fixtureStatus)"
call fixtureRepair draft-name 'Fixed after Keep editing'
call fixtureRepair wm-close '' || true
gone
jq -e '.automations["paste-and-send"].name == "Fixed after Keep editing"' "$state" >/dev/null
start
call fixtureRepair draft-text 'Hello🙂'
call fixtureRepair close ''
idle
jq -e '.closeDialog and .pendingSmart and (.errors | length > 0)' >/dev/null <<< "$result"
jq -e '.automations["paste-and-send"].steps[3].text == "Text saved on close"' "$state" >/dev/null
call fixtureRepair keep ''
call fixtureRepair draft-text 'Recovered text'
call fixtureRepair close '' || true
gone
start
call fixtureRepair draft-delay 'invalid'
call fixtureRepair close ''
idle
jq -e '.closeDialog and .pendingSmart' >/dev/null <<< "$result"
call fixtureRepair discard '' || true
gone
jq -e '.automations["paste-and-send"].steps[1].ms == 375' "$state" >/dev/null
printf '%s\n' 'PASS: invalid edits retain drafts in the close dialog; Keep editing and Discard preserve the right values'
# Exact pending-draft reorder regression: invalid name prevents saving FIRST.
jq '.automations["paste-and-send"].steps = [{type:"text",text:"FIRST"},{type:"text",text:"SECOND"}]' "$state" > "$state.next"
mv "$state.next" "$state"
start
call fixtureRepair draft-name ''
call fixtureRepair draft-first-text 'EDITED FIRST'
call fixtureRepair move-step '{"index":0,"direction":1}'
idle
jq -e '.pendingSmart and .smartDrafts["paste-and-send"].steps == [{type:"text",text:"SECOND"},{type:"text",text:"EDITED FIRST"}] and (.smartDrafts["paste-and-send"] | has("steps.0.text") | not)' >/dev/null <<< "$result"
jq -e '.automations["paste-and-send"].steps | map(.text) == ["FIRST","SECOND"]' "$state" >/dev/null
call fixtureRepair draft-name 'Reordered action'
call fixtureRepair commit-drafts ''
idle
jq -e '.pendingSmart == false and (.config.automations["paste-and-send"].steps | map(.text)) == ["SECOND","EDITED FIRST"]' >/dev/null <<< "$result"
call fixtureRepair close '' || true
gone
jq -e '.automations["paste-and-send"] | .name == "Reordered action" and (.steps | map(.text)) == ["SECOND","EDITED FIRST"]' "$state" >/dev/null
printf '%s\n' 'PASS: empty name, edit FIRST, move below SECOND, fix name saves [SECOND, EDITED FIRST]'
start
call fixtureRepair step-picker-open ''
call fixtureRepair step-picker-change '{"type":"key","keys":["CTRL","V"]}'
# Emit the same signal as Use action, before the picker hides itself.
call fixtureRepair step-picker-use ''
idle
jq -e '.pendingSmart == false and .config.automations["paste-and-send"].steps == [{type:"text",text:"SECOND"},{type:"text",text:"EDITED FIRST"},{type:"key",keys:["CTRL","V"]}]' >/dev/null <<< "$result"
call fixtureRepair close '' || true
gone
jq -e '.automations["paste-and-send"].steps | length == 3' "$state" >/dev/null
printf '%s\n' 'PASS: add step, change Ctrl+C to Ctrl+V, Use action adds exactly one step'
for chord in V C; do
  jq '.automations["paste-and-send"].steps |= .[:2]' "$state" > "$state.next"
  mv "$state.next" "$state"
  start
  call fixtureRepair step-picker-open ''
  if [[ "$chord" == V ]]; then call fixtureRepair step-picker-change '{"type":"key","keys":["CTRL","V"]}'; fi
  call fixtureRepair close '' || true
  gone
  jq -e --arg chord "$chord" '.automations["paste-and-send"].steps == [{type:"text",text:"SECOND"},{type:"text",text:"EDITED FIRST"},{type:"key",keys:["CTRL",$chord]}]' "$state" >/dev/null
done
printf '%s\n' 'PASS: add step then close saves exactly one step, with an edited or unchanged shortcut'
