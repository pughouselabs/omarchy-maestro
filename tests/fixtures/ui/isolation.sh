#!/usr/bin/env bash
# Source before launching or querying a fixture app. Reuse only private /tmp
# runtime trees, so probes cannot connect to the real app or background service.
maestro_ui_private_path() { [[ $1 == /tmp/maestro-ui-* && $1 != *'/../'* && $1 != */.. ]]; }
if maestro_ui_private_path "${XDG_RUNTIME_DIR:-}"; then
  maestro_ui_probe_root=${XDG_RUNTIME_DIR%/runtime}
else
  maestro_ui_probe_root=$(mktemp -d /tmp/maestro-ui-isolation-XXXXXX)
  export XDG_RUNTIME_DIR="$maestro_ui_probe_root/runtime"
fi
for maestro_ui_kind in CONFIG STATE DATA CACHE; do
  maestro_ui_name="XDG_${maestro_ui_kind}_HOME"
  maestro_ui_current=${!maestro_ui_name:-}
  if ! maestro_ui_private_path "$maestro_ui_current"; then
    printf -v "$maestro_ui_name" '%s/%s' "$maestro_ui_probe_root" "${maestro_ui_kind,,}"
  fi
  export "$maestro_ui_name"
done
export XDG_RUNTIME_DIR MAESTRO_CONFIG_HOME="$XDG_CONFIG_HOME/maestro"
umask 077
mkdir -m 700 -p -- "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_STATE_HOME/maestro" "$XDG_DATA_HOME" "$XDG_CACHE_HOME"
export QT_QPA_PLATFORM=offscreen
unset HYPRLAND_INSTANCE_SIGNATURE WAYLAND_DISPLAY DISPLAY
unset maestro_ui_kind maestro_ui_name maestro_ui_current
