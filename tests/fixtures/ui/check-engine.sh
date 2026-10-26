#!/usr/bin/env bash
# Exercise the reviewed engine with private files and no daemon socket.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
export MAESTRO_UI_TEST=1
export MAESTRO_UI_ENGINE_ROOT
MAESTRO_UI_ENGINE_ROOT=$(mktemp -d /tmp/maestro-ui-engine-XXXXXX)
cli="$repo/tests/fixtures/ui/maestro-isolated"
"$cli" catalog --json > "$MAESTRO_UI_ENGINE_ROOT/catalog.json"
jq -e '.version == 1 and (.groups | length >= 7) and (.gesture_presets | length >= 4) and (.smart_action_templates | length >= 4)' "$MAESTRO_UI_ENGINE_ROOT/catalog.json" >/dev/null
jq -e '[.groups[].actions[].action | select(.type == "hyprland")] | length > 0 and all(has("dispatcher") and (has("dispatch") | not))' "$MAESTRO_UI_ENGINE_ROOT/catalog.json" >/dev/null
# Controls only reads identity, capabilities and settings. No daemon is started.
if pgrep -x solaar >/dev/null || pgrep -x logid >/dev/null || pgrep -x logiops >/dev/null; then
  echo 'Stop Solaar/logiops before the read-only controls check.' >&2; exit 1
fi
"$cli" controls --json > "$MAESTRO_UI_ENGINE_ROOT/controls.json"
jq -e '.daemon == false and (.devices | type == "array")' "$MAESTRO_UI_ENGINE_ROOT/controls.json" >/dev/null
jq -e 'all(.devices[]; has("battery") and (.battery == null or ((.battery.percent | type == "number") and (.battery.charging | type == "boolean") and (.battery.status | type == "string"))))' "$MAESTRO_UI_ENGINE_ROOT/controls.json" >/dev/null
"$cli" config get > "$MAESTRO_UI_ENGINE_ROOT/initial.json"
"$cli" config apply --stdin < "$repo/tests/fixtures/ui/config.json" > "$MAESTRO_UI_ENGINE_ROOT/applied.json"
jq -e '.ok and .reloaded == false' "$MAESTRO_UI_ENGINE_ROOT/applied.json" >/dev/null
"$cli" config get > "$MAESTRO_UI_ENGINE_ROOT/saved.json"
jq -e '.automations["paste-and-send"].steps | length == 3' "$MAESTRO_UI_ENGINE_ROOT/saved.json" >/dev/null
jq '.buttons.back = {type:"hyprland",dispatcher:"workspace",arg:"e+1"}' "$MAESTRO_UI_ENGINE_ROOT/saved.json" | "$cli" config apply --stdin > "$MAESTRO_UI_ENGINE_ROOT/change.json"
"$cli" config undo > "$MAESTRO_UI_ENGINE_ROOT/undo.json"
"$cli" config get | jq -e '.buttons.back == null' >/dev/null
"$cli" config backups --json > "$MAESTRO_UI_ENGINE_ROOT/backups.json"
backup=$(jq -r '.backups[0].name' "$MAESTRO_UI_ENGINE_ROOT/backups.json")
"$cli" config restore "$backup" | jq -e '.ok' >/dev/null
"$cli" config get > "$MAESTRO_UI_ENGINE_ROOT/before-invalid.json"
if jq '.buttons.back = {type:"key",keys:["INVALID"]}' "$MAESTRO_UI_ENGINE_ROOT/saved.json" | "$cli" config apply --stdin > "$MAESTRO_UI_ENGINE_ROOT/rejected.json"; then
  echo 'Invalid key was accepted' >&2; exit 1
fi
jq -e '.ok == false and .errors[0].path == "buttons.back.keys[0]"' "$MAESTRO_UI_ENGINE_ROOT/rejected.json" >/dev/null
"$cli" config get > "$MAESTRO_UI_ENGINE_ROOT/after-invalid.json"
cmp "$MAESTRO_UI_ENGINE_ROOT/before-invalid.json" "$MAESTRO_UI_ENGINE_ROOT/after-invalid.json"
if printf '%s\n' '{"type":"key","keys":["CTRL","C"]}' | "$cli" test-action --stdin > "$MAESTRO_UI_ENGINE_ROOT/test-action.json"; then
  echo 'test-action unexpectedly found a daemon' >&2; exit 1
fi
jq -e '.ok == false and (.errors[0].message | contains("requires the running"))' "$MAESTRO_UI_ENGINE_ROOT/test-action.json" >/dev/null
# Leave a populated config for an optional app run, still confined to this root.
"$cli" config apply --stdin < "$repo/tests/fixtures/ui/config.json" >/dev/null
printf '%s\n' 'PASS: real catalog, read-only controls, config get/apply/undo/backups/restore, rejected-write preservation, isolated test-action failure'
printf 'Isolated test directory: %s\n' "$MAESTRO_UI_ENGINE_ROOT"
