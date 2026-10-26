#!/usr/bin/env bash
# Position only the isolated preview window for reproducible captures. The app
# itself makes no compositor geometry requests and uses its implicit size.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
if [[ -n ${MAESTRO_UI_STATE:-} ]] && ! maestro_ui_private_path "$MAESTRO_UI_STATE"; then
  echo 'Fixture state must be under /tmp/maestro-ui-* with no parent-directory traversal.' >&2; exit 1
fi
export MAESTRO_CAPTURE_OFFSCREEN=1
call() { timeout 5s qs -p "$repo/app" ipc --any-display call maestro "$@"; }
for ((attempt=0; attempt<80; attempt++)); do
  result=$(call fixtureStatus 2>/dev/null || true)
  if jq -e '.config.version == 1 and .busy == false' >/dev/null 2>&1 <<< "$result"; then break; fi
  sleep 0.1
done
jq -e '.config.version == 1' >/dev/null <<< "$result"
if [[ -n ${MAESTRO_CAPTURE_THEME:-} ]]; then
  [[ "$MAESTRO_CAPTURE_THEME" =~ ^[a-z0-9-]+$ ]] || { echo 'Invalid capture theme' >&2; exit 1; }
  capture_theme_path="/usr/share/omarchy/themes/$MAESTRO_CAPTURE_THEME"
  [[ -f "$capture_theme_path/colors.toml" ]] || { echo "Theme colors not found: $capture_theme_path" >&2; exit 1; }
  call fixtureRepair theme-path "$capture_theme_path"
fi
monitor=${MAESTRO_CAPTURE_MONITOR:-DP-1}
window_width=${MAESTRO_CAPTURE_WIDTH:-1280}
window_height=${MAESTRO_CAPTURE_HEIGHT:-820}
jq -e --argjson width "$window_width" --argjson height "$window_height" '.metrics.width == $width and .metrics.height == $height' >/dev/null <<< "$result" || {
  echo 'Start the fixture app with matching MAESTRO_UI_WIDTH and MAESTRO_UI_HEIGHT' >&2; exit 1;
}
suffix=${MAESTRO_CAPTURE_SUFFIX:-}
if [[ "$monitor" != DP-1 ]]; then suffix="-$monitor"; fi
if [[ "$window_width" == 1000 ]]; then suffix="${suffix}-minimum"; fi
capture() {
  sleep 0.45
  call capture "/tmp/maestro-ui-$1$suffix-detail.png"
  captured=false
  for ((attempt=0; attempt<50; attempt++)); do
    if call fixtureStatus | jq -e '.captured' >/dev/null; then captured=true; break; fi
    sleep 0.1
  done
  if [[ "$captured" != true ]]; then echo "App export did not finish" >&2; exit 1; fi
  cp "/tmp/maestro-ui-$1$suffix-detail.png" "/tmp/maestro-ui-$1$suffix.png"
}
if (($# == 0)); then set -- home buttons picker shortcut command gestures wheel point point-bottom smart builder builder-bottom applications profiles profiles-manage backups backup-restore help welcome welcome-gesture welcome-starter defaults step-picker; fi
for screen in "$@"; do
  if [[ "$screen" == smart ]]; then call fixtureCheck assign-smart; sleep 0.2; fi
  call preview "$screen"
  capture "$screen"
done
call fixtureCheck profile
call preview buttons
capture inheritance
call fixtureCheck reset-profile
call fixtureStatus | jq '.metrics' > "/tmp/maestro-ui-metrics${suffix:-DP-1}.json"
printf 'PASS: captured app screens on %s at %sx%s\n' "$monitor" "$window_width" "$window_height"
