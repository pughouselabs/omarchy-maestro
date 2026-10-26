#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# A virtual environment records its absolute path in every entry point, so a
# staged tree would break once moved. Packagers should build a wheel instead.
if [[ -n ${DESTDIR:-} ]]; then
  printf 'install.sh installs for the current user only and does not support DESTDIR.\n' >&2
  printf 'To package Maestro, use packaging/arch/PKGBUILD or build a wheel (python -m build).\n' >&2
  exit 2
fi
if [[ ${1:-} == --window-rule-only ]]; then
  bash "$root/packaging/hypr/window-rule.sh" install
  exit
fi
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
bin_dir="${BIN_DIR:-$HOME/.local/bin}"
venv="$data_home/maestro/venv"
method_file="$data_home/maestro/install-method"

if command -v pipx >/dev/null 2>&1; then
  pipx install --force "$root"
  mkdir -p "$(dirname "$method_file")"
  printf 'pipx\n' > "$method_file"
else
  python3 -m venv "$venv"
  "$venv/bin/python" -m pip install "$root"
  mkdir -p "$bin_dir"
  ln -sfn "$venv/bin/maestro" "$bin_dir/maestro"
  ln -sfn "$venv/bin/maestrod" "$bin_dir/maestrod"
  printf 'venv\n' > "$method_file"
fi

printf 'Required: mouse access for the widget, settings app and command line (requires sudo):\n'
printf '  sudo install -D -m 0644 %q /etc/udev/rules.d/70-maestro.rules\n' "$root/packaging/udev/70-maestro.rules"
printf '  sudo udevadm control --reload-rules && sudo udevadm trigger\n'
printf 'Optional, only for the maestrod service (lets programs running as you create virtual input):\n'
printf '  sudo install -D -m 0644 %q /etc/udev/rules.d/71-maestro-uinput.rules\n' "$root/packaging/udev/71-maestro-uinput.rules"
printf '  sudo install -D -m 0644 %q /etc/modules-load.d/maestro-uinput.conf\n' "$root/packaging/modules-load/maestro-uinput.conf"
printf '  sudo modprobe uinput && sudo udevadm control --reload-rules && sudo udevadm trigger\n'
bash "$root/packaging/hypr/window-rule.sh" install
printf 'Installed Maestro. Ensure %s is on PATH.\n' "$bin_dir"
