#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
test_home=$(mktemp -d /tmp/maestro-ui-hypr-XXXXXX)
trap 'rm -rf "$test_home"' EXIT
hypr_config="$test_home/.config/hypr"
mkdir -p "$hypr_config"
printf '%s\n' '-- Personal configuration' 'local untouched = true' > "$hypr_config/hyprland.lua"
cp "$hypr_config/hyprland.lua" "$test_home/original"
rule() {
  env -u HYPRLAND_INSTANCE_SIGNATURE -u DESTDIR HOME="$test_home" XDG_CONFIG_HOME="$test_home/.config" bash "$repo/packaging/$1.sh" --window-rule-only
}
rule install
rule install
[[ $(rg -c -- '-- maestro$' "$hypr_config/hyprland.lua") == 1 ]]
[[ $(find "$hypr_config" -name 'hyprland.lua.maestro-backup-*' | wc -l) == 1 ]]
cmp "$repo/packaging/hypr/maestro.lua" "$hypr_config/maestro.lua"
rule uninstall
rule uninstall
cmp "$test_home/original" "$hypr_config/hyprland.lua"
[[ ! -e "$hypr_config/maestro.lua" ]]
printf '%s\n' '-- Preexisting custom rule' > "$hypr_config/maestro.lua"
rule install
rule uninstall
[[ $(cat "$hypr_config/maestro.lua") == '-- Preexisting custom rule' ]]
printf 'PASS: isolated window rule install/uninstall is reversible and idempotent; preexisting rule restored\n'
