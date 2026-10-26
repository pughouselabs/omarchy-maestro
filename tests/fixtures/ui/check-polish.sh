#!/usr/bin/env bash
# Exercise actual Quickshell controls and colors in a private runtime.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
probe=$(mktemp -d /tmp/maestro-ui-polish-XXXXXX)
export XDG_STATE_HOME="$probe/state" XDG_RUNTIME_DIR="$probe/runtime" XDG_CONFIG_HOME="$probe/config"
mkdir -m 700 -p "$XDG_STATE_HOME/maestro" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME"
printf '%s\n' '{"version":1,"completed":true}' > "$XDG_STATE_HOME/maestro/welcome.json"
export MAESTRO_CLI="$repo/app/tools/maestro-preview" MAESTRO_UI_STATE="$probe-config.json" MAESTRO_UI_TEST=1 QT_QPA_PLATFORM=offscreen
qs --no-duplicate -p "$repo/app" > "$probe/app.log" 2>&1 &
app_pid=$!
trap 'kill "$app_pid" 2>/dev/null || true; wait "$app_pid" 2>/dev/null || true' EXIT
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
for ((attempt=0;attempt<100;attempt++)); do
  result=$(call fixtureStatus 2>/dev/null || true)
  if jq -e '.config.version == 1 and .busy == false and .design.welcomeReady' >/dev/null 2>&1 <<< "$result"; then break; fi
  sleep 0.1
done
jq -e '.design.fixtureApps == ["Firefox","Terminal","Files","Code","Spotify"]' >/dev/null <<< "$result"
call fixtureRepair focus-probe ''
result=$(call fixtureStatus)
jq -e '.design.focusProbe | .controls >= 16 and .failures == [] and .mouseFailures == [] and .rings and .trapped and .order == ["hotspot-1","hotspot-2","hotspot-3","hotspot-4","hotspot-5","hotspot-6"]' >/dev/null <<< "$result" || { jq '.design.focusProbe' <<< "$result"; exit 1; }
printf 'PASS: actual controls show outer focus rings; six dots in order; modal focus cycles stay inside; fake apps only\n'
count=0
for colors in /usr/share/omarchy/themes/*/colors.toml; do
  call fixtureRepair theme "$(cat "$colors")"
  result=$(call fixtureStatus)
  jq -e '(.design.contrast | all(. >= 4.5)) and .design.uiBoundaryContrast >= 3' >/dev/null <<< "$result" || { echo "$colors"; jq '.design' <<< "$result"; exit 1; }
  count=$((count+1))
done
printf 'PASS: all %s installed Omarchy themes meet text 4.5:1 and control boundary 3:1 contrast\n' "$count"
if rg 'TypeError|ReferenceError|Binding loop|Failed to load|Cannot assign|Cannot open|Error:' "$probe/app.log"; then exit 1; fi
