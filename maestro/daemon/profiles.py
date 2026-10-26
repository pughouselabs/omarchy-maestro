"""Case-insensitive, deterministic glob matching. First app profile wins."""

from fnmatch import fnmatchcase

from .config import DEFAULTS, merge


def matches(match, fields):
    for key, pattern in match.items():
        value = fields.get(key)
        if isinstance(pattern, int):
            if value != pattern:
                return False
        elif not fnmatchcase(str(value or "").casefold(), pattern.casefold()):
            return False
    return True


def resolve(raw, device, window=None):
    options = merge(DEFAULTS, {k: v for k, v in raw.items() if k in DEFAULTS})
    for entry in raw.get("devices", []):
        if matches(entry["match"], device):
            options = merge(options, {k: v for k, v in entry.items() if k in DEFAULTS})
    selected = None
    for i, entry in enumerate(raw.get("profiles", [])):
        if window and matches(entry["match"], window):
            options = merge(options, {k: v for k, v in entry.items() if k in DEFAULTS})
            selected = entry.get("name", f"profile-{i + 1}")
            break
    options["profile"] = selected
    return options


def setting_rule(raw, device, key, field=None):
    """Name the last matching rule that provides a particular setting field."""
    source = "config.settings"
    for index, entry in enumerate(raw.get("devices", [])):
        settings = entry.get("settings", {})
        if (
            matches(entry["match"], device)
            and key in settings
            and (field is None or field in settings[key])
        ):
            source = f"config.devices[{index}]"
            if entry.get("name"):
                source += f" ({entry['name']})"
    return source
