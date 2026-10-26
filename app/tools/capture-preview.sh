#!/usr/bin/env bash
# Reproducible app exports. Never opens a real engine or changes desktop theme.
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
width=${MAESTRO_CAPTURE_WIDTH:-1280}
height=${MAESTRO_CAPTURE_HEIGHT:-820}
capture_theme=${MAESTRO_CAPTURE_THEME:-}
if [[ -n "$capture_theme" && ! "$capture_theme" =~ ^[a-z0-9-]+$ ]]; then echo "Invalid capture theme" >&2; exit 1; fi
theme=${MAESTRO_THEME_PATH:-/usr/share/omarchy/themes/tokyo-night}
if [[ -n "$capture_theme" ]]; then theme="/usr/share/omarchy/themes/$capture_theme"; fi
[[ -f "$theme/colors.toml" ]] || { echo "Theme colors not found: $theme" >&2; exit 1; }
export XDG_STATE_HOME
XDG_STATE_HOME=$(mktemp -d /tmp/maestro-ui-capture-state-XXXXXX)
export XDG_RUNTIME_DIR="$XDG_STATE_HOME/runtime" XDG_CONFIG_HOME="$XDG_STATE_HOME/config"
mkdir -m 700 -p "$XDG_STATE_HOME/maestro" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME"
printf '%s\n' '{"version":1,"completed":true}' > "$XDG_STATE_HOME/maestro/welcome.json"
export MAESTRO_UI_STATE="${XDG_STATE_HOME}-config.json"
jq 'del(.buttons.gesture) | .buttons.back = {type:"key",keys:["CTRL","C"]}' "$repo/tests/fixtures/ui/config.json" > "$MAESTRO_UI_STATE"
export QT_QPA_PLATFORM=offscreen MAESTRO_UI_TEST=1 MAESTRO_CLI="$repo/app/tools/maestro-preview"
export MAESTRO_UI_WIDTH="$width" MAESTRO_UI_HEIGHT="$height" MAESTRO_THEME_PATH="$theme"
# Use qs directly so this script can own and stop exactly its preview process.
# --no-duplicate prevents accidentally addressing another app for this worktree.
if qs -p "$repo/app" list --all --json | jq -e --arg path "$repo/app/shell.qml" '.[] | select(.config_path == $path)' >/dev/null 2>&1; then
  echo 'Close the preview for this worktree before capturing.' >&2; exit 1
fi
env -u WAYLAND_DISPLAY -u DISPLAY -u HYPRLAND_INSTANCE_SIGNATURE qs --no-duplicate -p "$repo/app" > "$XDG_STATE_HOME/app.log" 2>&1 &
preview_pid=$!
trap 'kill "$preview_pid" 2>/dev/null || true; wait "$preview_pid" 2>/dev/null || true' EXIT
export MAESTRO_CAPTURE_OFFSCREEN=1 MAESTRO_CAPTURE_WIDTH="$width" MAESTRO_CAPTURE_HEIGHT="$height"
capture_tag=${MAESTRO_CAPTURE_TAG:-}
[[ "$capture_tag" =~ ^[a-z0-9-]*$ ]] || { echo 'Invalid capture tag' >&2; exit 1; }
export MAESTRO_CAPTURE_SUFFIX="-capture-$(basename "$theme")-${width}x${height}${capture_tag:+-$capture_tag}"
if (($# == 0)); then
  set -- home buttons picker shortcut command gestures wheel point point-bottom smart builder builder-bottom applications profiles profiles-manage backups backup-restore smart-empty welcome welcome-gesture welcome-starter help help-credits help-shortcuts defaults step-picker
fi
"$repo/tests/fixtures/ui/capture-app.sh" "$@"
if [[ ${MAESTRO_PREVIEW_NO_MOUSE:-0} != 1 ]]; then
  "$repo/tests/fixtures/ui/check-geometry.sh"
  qs -p "$repo/app" ipc --any-display call maestro preview gestures
  sleep 0.25
  "$repo/tests/fixtures/ui/check-geometry.sh"
fi
# Offscreen's platform notices are expected; runtime QML errors are not.
if rg 'TypeError|ReferenceError|Binding loop|Failed to load|Cannot assign|Cannot open|Error:' "$XDG_STATE_HOME/app.log"; then exit 1; fi
# Stable review copies named by screen, theme and size.
for screen in "$@" inheritance; do
  source_file="/tmp/maestro-ui-$screen$MAESTRO_CAPTURE_SUFFIX"
  if [[ "$width" == 1000 ]]; then source_file="$source_file-minimum"; fi
  cp "$source_file-detail.png" "/tmp/maestro-ui-review-$screen${capture_tag:+-$capture_tag}-$(basename "$theme")-${width}x${height}.png"
done
if command -v montage >/dev/null 2>&1; then
  montage_files=()
  for screen in "$@"; do montage_files+=("/tmp/maestro-ui-review-$screen${capture_tag:+-$capture_tag}-$(basename "$theme")-${width}x${height}.png"); done
  montage "${montage_files[@]}" -thumbnail 384x246 -tile 4x -geometry +8+8 -background '#d9dce3' "/tmp/maestro-ui-review-contact${capture_tag:+-$capture_tag}-$(basename "$theme")-${width}x${height}.png"
fi
printf 'Preview log: %s\n'  "$XDG_STATE_HOME/app.log"
