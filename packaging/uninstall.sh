#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n ${DESTDIR:-} ]]; then
  printf 'uninstall.sh removes the current user installation only and does not support DESTDIR.\n' >&2
  exit 2
fi
bash "$root/packaging/hypr/window-rule.sh" remove
if [[ ${1:-} == --window-rule-only ]]; then exit; fi
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
bin_dir="${BIN_DIR:-$HOME/.local/bin}"
venv="$data_home/maestro/venv"

# pipx install (by install.sh or by hand with `pipx install .`).
if command -v pipx >/dev/null 2>&1 && pipx list --short 2>/dev/null | grep -q '^maestro-mouse '; then
  pipx uninstall maestro-mouse
  printf 'Removed the pipx package maestro-mouse.\n'
fi
# Virtual environment fallback: remove only command links that point into it.
for name in maestro maestrod; do
  link="$bin_dir/$name"
  if [[ -L $link && $(readlink "$link") == "$venv/bin/$name" ]]; then
    rm -f "$link"
    printf 'Removed %s\n' "$link"
  fi
done
if [[ -d "$data_home/maestro" ]]; then
  rm -rf "$data_home/maestro"
  printf 'Removed %s\n' "$data_home/maestro"
fi
printf 'Remove the system udev rule with:\n  sudo rm -f /etc/udev/rules.d/70-maestro.rules\n'
printf 'Remove uinput module loading with:\n  sudo rm -f /etc/modules-load.d/maestro-uinput.conf\n'
printf 'Then reload rules with:\n  sudo udevadm control --reload-rules && sudo udevadm trigger\n'
printf 'Removed Maestro user installation.\n'
