#!/usr/bin/env bash
# Only the marked include belongs to Maestro. Preserve everything else.
set -euo pipefail
rule_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 - "$1" "$rule_root/maestro.lua" "${DESTDIR:-}${XDG_CONFIG_HOME:-$HOME/.config}/hypr" <<'PY'
import datetime
from pathlib import Path
import shutil
import sys

mode, source, directory = sys.argv[1:]
folder = Path(directory)
config = folder / 'hyprland.lua'
rule = folder / 'maestro.lua'
marker = 'require("hypr.maestro")  -- maestro'
if not config.exists():
    print('No Hyprland Lua config found; window rule skipped.')
    raise SystemExit(0)
text = config.read_text()
lines = text.splitlines(keepends=True)
clean = ''.join(line for line in lines if not line.rstrip().endswith('-- maestro'))
original = folder / 'maestro.lua.maestro-original'
if mode == 'install':
    content = Path(source).read_text()
    if rule.exists() and rule.read_text() != content and not original.exists():
        shutil.copy2(rule, original)
    if not rule.exists() or rule.read_text() != content:
        rule.write_text(content)
    if marker in text and clean != text:
        raise SystemExit(0)
    updated = []
    inserted = False
    for line in clean.splitlines(keepends=True):
        updated.append(line)
        if not inserted and 'personal configuration' in line.lower():
            if not line.endswith('\n'):
                updated.append('\n')
            updated.append(marker + '\n')
            inserted = True
    if not inserted:
        updated.append(('\n' if clean and not clean.endswith('\n') else '') + marker + '\n')
    changed = ''.join(updated)
else:
    changed = clean
    if original.exists():
        shutil.copy2(original, rule)
        original.unlink()
    elif rule.exists() and rule.read_text() == Path(source).read_text():
        rule.unlink()
if changed != text:
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = config.with_name(config.name + '.maestro-backup-' + stamp)
    shutil.copy2(config, backup)
    config.write_text(changed)
    print(f'Hyprland config backup: {backup}')
PY
if [[ -z ${DESTDIR:-} && -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]] && command -v hyprctl >/dev/null; then
  hyprctl reload
fi
