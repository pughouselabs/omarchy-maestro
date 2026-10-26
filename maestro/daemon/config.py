"""Validated JSON configuration with last-good reload and atomic persistence."""

from __future__ import annotations

import copy
import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .hyprland import build_dispatch
from .uinput import BUTTONS, key_code, text_codes


class ConfigError(ValueError):
    pass


DESKTOP_ACTIONS = {
    "apps",
    "menu",
    "app_switcher",
    "fullscreen",
    "workspace_previous",
    "workspace_next",
}
BUTTON_NAMES = {"gesture", "back", "forward", "middle", "mode_shift"}
DEFAULTS = {
    "settings": {},
    "buttons": {},
    "gesture": {
        "enabled": True,
        "button": "gesture",
        "threshold": 50,
        "tap": {"type": "desktop", "action": "app_switcher"},
        "left": {"type": "desktop", "action": "workspace_previous"},
        "right": {"type": "desktop", "action": "workspace_next"},
        "up": {"type": "desktop", "action": "fullscreen"},
        "down": {"type": "desktop", "action": "menu"},
    },
    "thumb_wheel": {"mode": "horizontal", "step": 120},
}
MAX_STEPS = 50
MAX_DELAY_MS = 30000
MAX_TEXT = 500
MAX_DEPTH = 3
AUTOMATION_ID = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
BACKUP_NAME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}(?:-(?:\d{2}|\d{12}))?\Z")


def _error(path, message):
    raise ConfigError(f"{path}: {message}")


def _object(value, path, allowed):
    if not isinstance(value, dict):
        _error(path, "expected an object")
    for key in value:
        if key not in allowed:
            _error(f"{path}.{key}", "unknown option")


def _integer(value, path, low, high):
    if type(value) is not int or not low <= value <= high:
        _error(path, f"expected an integer from {low} to {high}")


def validate_settings(value, path="settings"):
    _object(value, path, {"dpi", "smartshift", "invert"})
    if "dpi" in value:
        _integer(value["dpi"], f"{path}.dpi", 1, 65535)
    if "invert" in value and type(value["invert"]) is not bool:
        _error(f"{path}.invert", "expected true or false")
    if "smartshift" in value:
        setting = value["smartshift"]
        _object(setting, f"{path}.smartshift", {"mode", "threshold"})
        if "mode" in setting and setting["mode"] not in ("ratchet", "freespin"):
            _error(f"{path}.smartshift.mode", "expected ratchet or freespin")
        if "threshold" in setting:
            _integer(setting["threshold"], f"{path}.smartshift.threshold", 1, 255)


def validate_action(value, path, automations=None, *, step=False):
    if value is None:
        if step:
            _error(path, "a sequence step must be an action object")
        return
    if not isinstance(value, dict):
        _error(path, "expected an action object or null (native button)")
    kind = value.get("type")
    fields = {
        "key": {"type", "keys"},
        "mouse": {"type", "button"},
        "command": {"type", "argv"},
        "desktop": {"type", "action"},
        "none": {"type"},
        "hyprland": {"type", "dispatcher", "arg"},
        "sequence": {"type", "steps"},
        "automation": {"type", "id"},
        "text": {"type", "text"},
        "delay": {"type", "ms"},
    }
    if not isinstance(kind, str) or kind not in fields:
        _error(f"{path}.type", "unknown action type")
    if step and kind in ("none", "sequence"):
        _error(f"{path}.type", "this action is not a sequence step")
    if not step and kind in ("text", "delay"):
        _error(f"{path}.type", "text and delay are sequence steps only")
    _object(value, path, fields[kind])
    if kind == "key":
        keys = value.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 16:
            _error(f"{path}.keys", "expected 1-16 Linux key names")
        codes = []
        for i, key in enumerate(keys):
            try:
                codes.append(key_code(key))
            except ValueError as exc:
                _error(f"{path}.keys[{i}]", str(exc))
        if len(set(codes)) != len(codes):
            _error(f"{path}.keys", "duplicate key")
    elif kind == "mouse" and (
        not isinstance(value.get("button"), str) or value["button"] not in BUTTONS
    ):
        _error(f"{path}.button", "expected left, right, middle, back, forward, side, or extra")
    elif kind == "command":
        argv = value.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 128
            or any(not isinstance(a, str) or not a or "\x00" in a for a in argv)
        ):
            _error(
                f"{path}.argv", "expected a nonempty list of nonempty strings, without NUL bytes"
            )
    elif kind == "desktop" and (
        not isinstance(value.get("action"), str) or value["action"] not in DESKTOP_ACTIONS
    ):
        _error(f"{path}.action", "unknown desktop action")
    elif kind == "hyprland":
        try:
            build_dispatch(value)
        except ValueError as exc:
            field = "dispatcher" if "dispatcher" in str(exc) else "arg"
            _error(f"{path}.{field}", str(exc))
    elif kind == "text":
        text = value.get("text")
        if not isinstance(text, str) or len(text) > 500:
            _error(f"{path}.text", "expected text of at most 500 characters")
        try:
            text_codes(text)
        except ValueError as exc:
            _error(f"{path}.text", str(exc))
    elif kind == "delay":
        _integer(value.get("ms"), f"{path}.ms", 0, 5000)
    elif kind == "sequence":
        validate_steps(value.get("steps"), f"{path}.steps", automations)
    elif kind == "automation":
        ident = value.get("id")
        if not isinstance(ident, str) or not AUTOMATION_ID.fullmatch(ident):
            _error(f"{path}.id", "expected an automation id (lowercase letters, digits, hyphens)")
        if automations is not None and ident not in automations:
            _error(f"{path}.id", "unknown automation id")


def validate_steps(steps, path, automations=None):
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        _error(path, "expected 1-50 steps")
    delay = 0
    for i, step in enumerate(steps):
        validate_action(step, f"{path}[{i}]", automations, step=True)
        if step["type"] == "delay":
            delay += step["ms"]
    if delay > MAX_DELAY_MS:
        _error(path, "total delays must not exceed 30000 ms")


def validate_expanded_action(action, automations, path):
    """Count concrete steps after automation references have been expanded."""
    if not action or action.get("type") not in ("sequence", "automation"):
        return
    depth = 1 if action["type"] == "automation" else 0
    steps = automations[action["id"]]["steps"] if depth else action["steps"]
    stack = [(iter(steps), depth)]
    count = text_length = delay = 0
    while stack:
        step = next(stack[-1][0], None)
        if step is None:
            stack.pop()
            continue
        if step["type"] == "automation":
            depth = stack[-1][1] + 1
            if depth > MAX_DEPTH:
                _error(path, "automation nesting exceeds 3 levels")
            stack.append((iter(automations[step["id"]]["steps"]), depth))
            continue
        count += 1
        if count > MAX_STEPS:
            _error(path, "expanded sequence exceeds 50 steps")
        if step["type"] == "text":
            text_length += len(step["text"])
            if text_length > MAX_TEXT:
                _error(path, "expanded sequence text exceeds 500 characters")
        elif step["type"] == "delay":
            delay += step["ms"]
            if delay > MAX_DELAY_MS:
                _error(path, "expanded sequence delays exceed 30000 ms")


def _button(value, path):
    if not isinstance(value, str) or value not in BUTTON_NAMES:
        _error(path, "expected gesture, back, forward, middle, or mode_shift")


def _options(value, path, settings=True, automations=None):
    fields = {"buttons", "gesture", "thumb_wheel"} | ({"settings"} if settings else set())
    _object(value, path, fields)
    if "settings" in value:
        validate_settings(value["settings"], f"{path}.settings")
    if "buttons" in value:
        buttons = value["buttons"]
        _object(buttons, f"{path}.buttons", BUTTON_NAMES)
        for button, action in buttons.items():
            validate_action(action, f"{path}.buttons.{button}", automations)
    if "gesture" in value:
        gesture = value["gesture"]
        _object(
            gesture,
            f"{path}.gesture",
            {"enabled", "button", "threshold", "tap", "up", "down", "left", "right"},
        )
        if "enabled" in gesture and type(gesture["enabled"]) is not bool:
            _error(f"{path}.gesture.enabled", "expected true or false")
        if "button" in gesture:
            _button(gesture["button"], f"{path}.gesture.button")
        if "threshold" in gesture:
            _integer(gesture["threshold"], f"{path}.gesture.threshold", 1, 10000)
        for direction in ("tap", "up", "down", "left", "right"):
            if direction in gesture:
                validate_action(gesture[direction], f"{path}.gesture.{direction}", automations)
    if "thumb_wheel" in value:
        wheel = value["thumb_wheel"]
        _object(wheel, f"{path}.thumb_wheel", {"mode", "step", "left", "right"})
        if "mode" in wheel and wheel["mode"] not in (
            "horizontal",
            "volume",
            "zoom",
            "tabs",
            "workspaces",
            "custom",
        ):
            _error(
                f"{path}.thumb_wheel.mode",
                "expected horizontal, volume, zoom, tabs, workspaces, or custom",
            )
        if "step" in wheel:
            _integer(wheel["step"], f"{path}.thumb_wheel.step", 1, 32767)
        for direction in ("left", "right"):
            if direction in wheel:
                validate_action(wheel[direction], f"{path}.thumb_wheel.{direction}", automations)
        if wheel.get("mode") == "custom" and not all(d in wheel for d in ("left", "right")):
            _error(f"{path}.thumb_wheel", "custom mode requires left and right actions")


def validate(raw):
    _object(
        raw,
        "config",
        {
            "version",
            "settings",
            "buttons",
            "gesture",
            "thumb_wheel",
            "devices",
            "profiles",
            "hyprland_dispatch",
            "automations",
        },
    )
    if type(raw.get("version", 1)) is not int or raw.get("version", 1) != 1:
        _error("config.version", "only version 1 is supported")
    if raw.get("hyprland_dispatch", "auto") not in ("auto", "lua", "legacy"):
        _error("config.hyprland_dispatch", "expected auto, lua, or legacy")
    automations = raw.get("automations", {})
    if not isinstance(automations, dict):
        _error("config.automations", "expected an object")
    for ident, definition in automations.items():
        path = f"config.automations.{ident}"
        if not isinstance(ident, str) or not AUTOMATION_ID.fullmatch(ident):
            _error(path, "expected a lowercase id using letters, digits, and hyphens")
        _object(definition, path, {"name", "description", "steps"})
        for field in ("name", "description"):
            value = definition.get(field)
            if not isinstance(value, str) or not value or len(value) > 500:
                _error(f"{path}.{field}", "expected a nonempty string of at most 500 characters")
        validate_steps(definition.get("steps"), f"{path}.steps", automations)

    graph = {
        ident: [step["id"] for step in definition["steps"] if step["type"] == "automation"]
        for ident, definition in automations.items()
    }
    done = set()
    for root in graph:
        if root in done:
            continue
        stack = [(root, iter(graph[root]))]
        active = {root}
        while stack:
            ident, children = stack[-1]
            child = next(children, None)
            if child is None:
                active.remove(ident)
                done.add(ident)
                stack.pop()
            elif child in active:
                _error(f"config.automations.{child}", "automation reference cycle")
            elif child not in done:
                active.add(child)
                stack.append((child, iter(graph[child])))
    for ident in automations:
        validate_expanded_action(
            {"type": "automation", "id": ident}, automations, f"config.automations.{ident}"
        )
    _options({k: v for k, v in raw.items() if k in DEFAULTS}, "config", automations=automations)
    for group, allowed in (
        ("devices", {"name", "path", "index"}),
        ("profiles", {"class", "title"}),
    ):
        entries = raw.get(group, [])
        if not isinstance(entries, list):
            _error(f"config.{group}", "expected a list")
        for i, entry in enumerate(entries):
            path = f"config.{group}[{i}]"
            option_fields = set(DEFAULTS) if group == "devices" else set(DEFAULTS) - {"settings"}
            _object(entry, path, option_fields | {"name", "match"})
            if "name" in entry and (not isinstance(entry["name"], str) or not entry["name"]):
                _error(f"{path}.name", "expected a nonempty label")
            match = entry.get("match")
            _object(match, f"{path}.match", allowed)
            if not match:
                _error(f"{path}.match", "at least one match field is required")
            for key, pattern in match.items():
                if key == "index":
                    _integer(pattern, f"{path}.match.index", 1, 255)
                elif not isinstance(pattern, str) or not pattern or len(pattern) > 1024:
                    _error(
                        f"{path}.match.{key}",
                        "expected a nonempty glob pattern (at most 1024 characters)",
                    )
            _options(
                {k: v for k, v in entry.items() if k in DEFAULTS},
                path,
                group == "devices",
                automations,
            )
    pending = [(raw, "config")]
    while pending:
        value, path = pending.pop()
        if isinstance(value, dict):
            if value.get("type") in ("sequence", "automation"):
                validate_expanded_action(value, automations, path)
            pending.extend((child, f"{path}.{key}") for key, child in value.items())
        elif isinstance(value, list):
            pending.extend((child, f"{path}[{i}]") for i, child in enumerate(value))
    return copy.deepcopy(raw)


def merge(base, overlay):
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict) and "type" not in value:
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def default_path():
    override = os.environ.get("MAESTRO_CONFIG_HOME")
    if override:
        return Path(override) / "config.json"
    return (
        Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        / "maestro/config.json"
    )


def full_config(raw):
    return merge(
        {
            "version": 1,
            **DEFAULTS,
            "hyprland_dispatch": "auto",
            "devices": [],
            "profiles": [],
            "automations": {},
        },
        raw,
    )


def _decode(data):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ConfigError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    try:
        return validate(json.loads(data, object_pairs_hook=pairs))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ConfigError(f"invalid JSON: {exc}") from exc


class ConfigFile:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.raw = {}
        self.error = None
        self._stamp = None
        self._loaded_stamp = None
        self.reload()

    def stamp(self):
        try:
            stat = self.path.stat()
            return stat.st_ino, stat.st_mtime_ns, stat.st_size
        except FileNotFoundError:
            return None

    def reload(self):
        try:
            stamp = self.stamp()
            data = self.path.read_bytes() if stamp is not None else b"{}"
            raw = _decode(data)
        except (OSError, ConfigError) as exc:
            self.error = f"{self.path}: {exc}"
            # Remember an invalid edit so the poller does not log it repeatedly.
            self._stamp = self.stamp()
            return False
        self.raw, self.error = raw, None
        self._stamp = self._loaded_stamp = stamp
        return True

    def changed(self):
        return self.stamp() != self._stamp

    @staticmethod
    def _atomic(path, data):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_device_settings(self, name, path, index, settings):
        validate_settings(settings)
        if self.error or self.stamp() != self._loaded_stamp:
            raise ConfigError("config changed or is invalid; reload it before saving settings")
        raw = copy.deepcopy(self.raw)
        # A precise entry goes last, after any broader user-created device rules.
        # hidraw numbers can change after unplugging a receiver. Model + slot
        # survives that change; users with identical mice can add a path rule.
        match = {"name": name, "index": index}
        entries = raw.setdefault("devices", [])
        position = next(
            (i for i in range(len(entries) - 1, -1, -1) if entries[i]["match"] == match), None
        )
        if position is None or position != len(entries) - 1:
            # A narrow final override preserves unrelated settings and button
            # mappings from later user rules. Repeated updates reuse it.
            entry = {"match": match, "settings": {}}
        else:
            entry = entries.pop(position)
        entry["settings"] = merge(entry.get("settings", {}), settings)
        # A saved request always wins later wildcard and path rules.
        entries.append(entry)
        self.replace(raw)

    def replace(self, raw, *, backup=True):
        """Atomically commit validated config, or restore a failed IPC transaction."""
        if self.error or self.stamp() != self._loaded_stamp:
            raise ConfigError("config changed or is invalid; reload it before saving settings")
        validate(raw)
        if backup and self.path.exists():
            self._atomic(self.path.with_suffix(self.path.suffix + ".bak"), self.path.read_bytes())
        self._atomic(self.path, (json.dumps(raw, indent=2) + "\n").encode())
        self.raw = copy.deepcopy(raw)
        self._stamp = self._loaded_stamp = self.stamp()

    @property
    def backup_dir(self):
        return self.path.parent / "backups"

    @staticmethod
    def _sequence(path):
        stem = path.stem
        return int(stem[-12:]) if len(stem) == 32 else 0

    @contextmanager
    def _backup_lock(self):
        directory = self.backup_dir
        if directory.is_symlink():
            raise ConfigError("refusing a symlinked backup directory")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        fd = os.open(
            directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield directory
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _backup_files(self):
        if not self.backup_dir.exists():
            return []
        return sorted(
            (
                path
                for path in self.backup_dir.glob("*.json")
                if BACKUP_NAME.fullmatch(path.stem) and path.is_file() and not path.is_symlink()
            ),
            key=lambda path: (
                self._sequence(path),
                path.stem[:19],
                int(path.stem[20:]) if len(path.stem) == 22 else 0,
            ),
            reverse=True,
        )

    def backups(self):
        return [
            {"name": path.stem, "time": path.stem[:11] + path.stem[11:19].replace("-", ":")}
            for path in self._backup_files()
        ]

    def apply(self, raw):
        validate(raw)
        with self._backup_lock() as directory:
            return self._apply_locked(raw, directory)

    def _apply_locked(self, raw, directory):
        if self.error or self.stamp() != self._loaded_stamp:
            raise ConfigError("config changed or is invalid; reload it before applying")
        counter = directory / ".sequence"
        if counter.is_symlink():
            raise ConfigError("refusing a symlinked backup sequence counter")
        if counter.exists():
            try:
                sequence = int(counter.read_text()) + 1
            except ValueError as exc:
                raise ConfigError("backup sequence counter is invalid") from exc
        else:
            redo = directory / "redo"
            files = self._backup_files() + (list(redo.glob("*.json")) if redo.is_dir() else [])
            sequence = max((self._sequence(path) for path in files), default=0) + 1
        self._atomic(counter, str(sequence).encode())
        name = f"{datetime.now():%Y-%m-%dT%H-%M-%S}-{sequence:012d}"
        backup = directory / f"{name}.json"
        previous = self.path.read_bytes() if self.path.exists() else b"{}\n"
        self._atomic(backup, previous)
        try:
            self.replace(raw, backup=False)
        except Exception:
            backup.unlink()
            raise
        for old in self._backup_files()[20:]:
            old.unlink()
        return name

    def restore(self, name):
        if not isinstance(name, str) or not BACKUP_NAME.fullmatch(name):
            raise ConfigError("invalid backup name")
        path = self.backup_dir / f"{name}.json"
        if not path.exists():
            if (self.backup_dir / "redo").is_symlink():
                raise ConfigError("refusing a symlinked redo directory")
            path = self.backup_dir / "redo" / f"{name}.json"
        if path.is_symlink():
            raise ConfigError("refusing a symlinked backup")
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise ConfigError("backup not found") from exc
        return self.apply(_decode(data))

    def undo(self, *, finalize=True):
        with self._backup_lock() as directory:
            files = self._backup_files()
            if not files:
                raise ConfigError("no configuration backup to undo")
            target = files[0]
            raw = _decode(target.read_bytes())
            if self.error or self.stamp() != self._loaded_stamp:
                raise ConfigError("config changed or is invalid; reload it before undoing")
            previous = self.path.read_bytes() if self.path.exists() else b"{}\n"
            if finalize:
                redo = self._prepare_undo_locked(directory, target.stem, previous)
            try:
                self.replace(raw, backup=False)
            except Exception:
                if finalize:
                    try:
                        if self.path.read_bytes() != previous:
                            self._atomic(self.path, previous)
                            self.raw = _decode(previous)
                            self._stamp = self._loaded_stamp = self.stamp()
                    finally:
                        redo.unlink(missing_ok=True)
                raise
            if finalize:
                try:
                    self._finish_undo_locked(directory, target.stem, redo)
                except Exception:
                    try:
                        self.replace(_decode(previous), backup=False)
                    finally:
                        redo.unlink(missing_ok=True)
                    raise
            return target.stem

    def finalize_undo(self, name, previous):
        with self._backup_lock() as directory:
            self._finalize_undo_locked(directory, name, previous)

    def _finalize_undo_locked(self, directory, name, previous):
        redo = self._prepare_undo_locked(directory, name, previous)
        self._finish_undo_locked(directory, name, redo)

    def _prepare_undo_locked(self, directory, name, previous):
        target = directory / f"{name}.json"
        if not BACKUP_NAME.fullmatch(name) or target.is_symlink() or not target.is_file():
            raise ConfigError("undo backup is no longer available")
        redo_dir = directory / "redo"
        if redo_dir.is_symlink():
            raise ConfigError("refusing a symlinked redo directory")
        redo_dir.mkdir(mode=0o700, exist_ok=True)
        redo_dir.chmod(0o700)
        redo = redo_dir / target.name
        if redo.exists() or redo.is_symlink():
            raise ConfigError("undo redo backup already exists")
        try:
            self._atomic(redo, previous)
        except Exception:
            redo.unlink(missing_ok=True)
            raise
        return redo

    def _finish_undo_locked(self, directory, name, redo):
        target = directory / f"{name}.json"
        try:
            target.unlink()
        except Exception:
            redo.unlink()
            raise
        redo_dir = redo.parent
        try:
            for old in sorted(
                redo_dir.glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True
            )[20:]:
                old.unlink()
        except OSError:
            pass
