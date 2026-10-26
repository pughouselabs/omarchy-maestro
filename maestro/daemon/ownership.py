"""A small record of which mouse controls Maestro diverted, kept across reboots.

A receiver keeps a mouse powered while the computer restarts, so a diversion
can outlive a daemon that crashed or lost power. This record lets the next run
say that Maestro probably left a control taken and offer to release it. It never
proves who holds the control now, so nothing is ever released automatically;
only the user's explicit Release button writes to the mouse.

Each mouse is keyed by its model, its connection and a SHA-256 hash of the
unit ID it reports through HID++ feature 0x0003 (device information). The raw
unit ID is never stored, logged or shown. The hash is pseudonymous, not
anonymous: the same mouse always gives the same hash. A mouse that reports no
usable unit ID gets no record at all and is read-only: nothing, not even an
explicit release, is written to it (see events.UnitGate).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import stat
import tempfile
import time
from pathlib import Path

from maestro import hidpp

LOG = logging.getLogger("maestrod")
VERSION = 2
MAX_BYTES = 64 * 1024
MAX_DEVICES = 32
MAX_CONTROLS = 16
MAX_TIMESTAMP = 2.0**40  # far beyond any real clock, small enough to stay exact
KEY = re.compile(r"[A-Za-z0-9 ._()+-]{1,64}\|[a-z]{1,16}\|[0-9a-f]{64}\Z")
CONTROL_ID = re.compile(r"0x[0-9a-f]{4}\Z")
RECORD_PROBLEM = "Can't save the button record; gestures are off until this is fixed."

# Apps that may divert MX mouse controls. Matched against the process name and
# the first two argv entries (interpreters run scripts by path).
OTHER_OWNERS = (
    "solaar",
    "logid",
    "logiops",
    "openlogi",
    "logitune",
    "juhradial",
    "mx-options",
    "input-remapper",
)
MAX_PROCESSES = 65536
MAX_CMDLINE = 4096


class RecordError(OSError):
    """The ownership record could not be saved durably."""


def default_path():
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "maestro" / "diversions.json"


def unit_id(device):
    """The 4-byte unit ID from HID++ 0x0003, or None when it is missing or blank."""
    try:
        if not device.has(hidpp.FW_VERSION):
            return None
        data = bytes(device.call(hidpp.FW_VERSION, 0)[1:5])
    except (hidpp.HidppError, hidpp.NoResponse, OSError, AttributeError, TypeError):
        return None
    if len(data) != 4 or data in (b"\0" * 4, b"\xff" * 4):
        return None
    return data


def device_key(device):
    """Unique per physical mouse and connection; None when that cannot be verified."""
    model = getattr(device, "model", None)
    node = getattr(device, "node", None)
    connection = getattr(node, "connection", None)
    if not isinstance(model, str) or not isinstance(connection, str):
        return None
    unit = unit_id(device)
    if unit is None:
        return None
    digest = hashlib.sha256(b"maestro-unit-id\0" + model.encode() + b"\0" + unit).hexdigest()
    key = f"{model}|{connection}|{digest}"
    return key if KEY.match(key) else None


def selector_tag(key):
    """A short pseudonymous tag for one physical mouse, derived from its record key.

    The settings app and the CLI send it back with an explicit release so the
    service can refuse when a different mouse now sits at the chosen position.
    None when the mouse reports no usable unit ID.
    """
    if key is None:
        return None
    return hashlib.sha256(b"maestro-selector\0" + key.encode()).hexdigest()[:16]


def _process_names(entry):
    names = set()
    try:
        with open(entry / "comm", "rb") as stream:
            names.add(stream.read(64).decode(errors="replace").strip())
    except OSError:
        pass
    try:
        with open(entry / "cmdline", "rb") as stream:
            args = stream.read(MAX_CMDLINE).split(b"\0")[:2]
    except OSError:
        args = []
    names.update(Path(a.decode(errors="replace")).name for a in args if a)
    return names


def find_other_owner(proc=Path("/proc"), owners=OTHER_OWNERS):
    """(pid, name) of a running app that may divert mouse controls, else None."""
    try:
        for count, entry in enumerate(proc.iterdir()):
            if count >= MAX_PROCESSES:
                break
            if not entry.name.isdigit():
                continue
            for name in _process_names(entry):
                base = name.removesuffix(".py")
                for owner in owners:
                    if base == owner or base.startswith(owner + "-"):
                        return entry.name, owner
    except OSError:
        return None
    return None


def _valid_timestamp(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= MAX_TIMESTAMP
    )


def _flags(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 0xFF


def _parse(data):
    raw = json.loads(data)
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        raise ValueError("unknown format")
    devices = raw.get("devices")
    if not isinstance(devices, dict) or len(devices) > MAX_DEVICES:
        raise ValueError("bad device list")
    result = {}
    for key, entry in devices.items():
        if not isinstance(key, str) or not KEY.match(key) or not isinstance(entry, dict):
            raise ValueError("bad device entry")
        controls = entry.get("controls")
        thumb = entry.get("thumb")
        updated = entry.get("updated", 0)
        if (
            not isinstance(controls, dict)
            or len(controls) > MAX_CONTROLS
            or not (thumb is None or _flags(thumb))
            or not _valid_timestamp(updated)
        ):
            raise ValueError("bad device entry")
        parsed = {}
        for cid, item in controls.items():
            if (
                not isinstance(cid, str)
                or not CONTROL_ID.match(cid)
                or not isinstance(item, dict)
                or not isinstance(item.get("raw_xy"), bool)
                or not _flags(item.get("flags"))
            ):
                raise ValueError("bad control entry")
            parsed[int(cid, 16)] = (item["raw_xy"], item["flags"])
        result[key] = {"controls": parsed, "thumb": thumb, "updated": float(updated)}
    return result


def _serialize(devices):
    body = {
        "version": VERSION,
        "devices": {
            key: {
                "controls": {
                    f"{cid:#06x}": {"raw_xy": bool(raw), "flags": int(flags)}
                    for cid, (raw, flags) in sorted(entry["controls"].items())
                },
                "thumb": entry["thumb"],
                "updated": round(entry["updated"], 3),
            }
            for key, entry in devices.items()
        },
    }
    return (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()


def _private_directory(path):
    """Create or accept only a real directory owned by this user, then make it private."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RecordError(f"{path} is not a private directory owned by this user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(path, 0o700)


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class DiversionLedger:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else default_path()
        self.warned = set()

    def _warn(self, reason, message, *args):
        if reason not in self.warned:
            self.warned.add(reason)
            LOG.warning(message, *args)

    def _read(self):
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(self.path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("not a regular file")
            if info.st_uid != os.getuid():
                raise ValueError("not owned by this user")
            chunks, size = [], 0
            while size <= MAX_BYTES:
                chunk = os.read(fd, MAX_BYTES + 1 - size)
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def load(self):
        try:
            data = self._read()
        except FileNotFoundError:
            return {}
        except OSError as exc:
            self._warn("read", "ignoring diversion record %s: %s", self.path, exc.strerror or exc)
            return {}
        except ValueError as exc:
            self._warn("type", "ignoring diversion record %s: %s", self.path, exc)
            return {}
        if len(data) > MAX_BYTES:
            self._warn("size", "ignoring diversion record %s: file is too large", self.path)
            return {}
        try:
            return _parse(data)
        except (ValueError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
            self._warn("format", "ignoring malformed diversion record %s: %s", self.path, exc)
            return {}

    def get(self, key):
        return self.load().get(key) if key is not None else None

    def update(self, key, controls, thumb):
        """Durably replace one device entry; an entry with nothing in it is removed.

        ``controls`` maps control ID to (raw_xy, flags) and ``thumb`` is the
        recorded thumb-wheel mode byte or None. Raises RecordError when the
        change could not be saved, so a caller can refuse to divert.
        """
        if key is None:
            return
        controls = {int(cid): (bool(raw), int(flags)) for cid, (raw, flags) in controls.items()}
        if len(controls) > MAX_CONTROLS or not (thumb is None or _flags(thumb)):
            raise RecordError("diversion record entry is out of range")
        devices = self.load()
        current = devices.get(key)
        if not controls and thumb is None:
            if current is None:
                return
            del devices[key]
        else:
            if (
                current is not None
                and current["controls"] == controls
                and current["thumb"] == thumb
            ):
                return
            devices[key] = {"controls": controls, "thumb": thumb, "updated": time.time()}
            while len(devices) > MAX_DEVICES:
                del devices[min(devices, key=lambda k: devices[k]["updated"])]
        try:
            self._write(devices)
        except RecordError:
            raise
        except (OSError, ValueError) as exc:
            raise RecordError(f"could not save diversion record {self.path}: {exc}") from exc

    def _write(self, devices):
        parent = self.path.parent
        _private_directory(parent)
        try:
            info = os.lstat(self.path)
        except FileNotFoundError:
            info = None
        if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()):
            raise RecordError(f"{self.path} is not a regular file owned by this user")
        if not devices:
            if info is not None:
                os.unlink(self.path)
                _fsync_directory(parent)
            return
        data = _serialize(devices)
        if len(data) > MAX_BYTES:
            raise RecordError("diversion record would exceed its size limit")
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(parent)
        finally:
            if os.path.lexists(temporary):
                os.unlink(temporary)
