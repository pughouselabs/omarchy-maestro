#!/usr/bin/env bash
# Six real launcher processes, one private offscreen app, no real config or mouse.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
launch_root=$(mktemp -d /tmp/maestro-ui-launchers-XXXXXX)
mkdir -m 700 "$launch_root/runtime"
app_pid=''
cleanup() {
  if [[ -n "$app_pid" ]]; then kill "$app_pid" 2>/dev/null || true; fi
  rm -rf -- "$launch_root"
}
trap cleanup EXIT
private_qs() { env XDG_RUNTIME_DIR="$launch_root/runtime" qs "$@"; }
pids=()
for ((index=0; index<6; index++)); do
  env -u WAYLAND_DISPLAY -u DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE QT_QPA_PLATFORM=offscreen \
    XDG_RUNTIME_DIR="$launch_root/runtime" MAESTRO_CLI="$repo/tests/fixtures/ui/maestro-fake" \
    MAESTRO_UI_STATE=/tmp/maestro-ui-launcher-state.json MAESTRO_UI_TEST=1 \
    "$repo/bin/maestro-settings" > "$launch_root/launch-$index.log" 2>&1 &
  pids+=("$!")
done
for ((attempt=0; attempt<100; attempt++)); do
  result=$(private_qs -p "$repo/app" ipc --any-display call maestro fixtureStatus 2>/dev/null || true)
  if jq -e '.config.version == 1 and .focusRequests >= 6' >/dev/null 2>&1 <<< "$result"; then break; fi
  sleep 0.1
done
instances=$(private_qs list --all -j)
jq -e --arg path "$repo/app/shell.qml" '[.[] | select(.config_path==$path)] | length == 1' >/dev/null <<< "$instances"
app_pid=$(jq -r --arg path "$repo/app/shell.qml" '.[] | select(.config_path==$path) | .pid' <<< "$instances")
jq -e '.focusRequests >= 6' >/dev/null <<< "$result"
if flock -n "$launch_root/runtime/maestro-settings.lock" true; then
  echo 'Launcher lock was released while the app is still running' >&2; exit 1
fi
for pid in "${pids[@]}"; do
  if [[ "$pid" != "$app_pid" ]]; then wait "$pid"; fi
done
kill "$app_pid"
wait "$app_pid" 2>/dev/null || true
app_pid=''
flock -n "$launch_root/runtime/maestro-settings.lock" true
printf '%s\n' 'PASS: six concurrent launches produce one app, five focus requests, and a lifetime lock'
