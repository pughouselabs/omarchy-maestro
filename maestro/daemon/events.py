"""HID++ event capture and reversible, mouse-only diversion."""

from __future__ import annotations

import logging
import struct
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass

from maestro import hidpp

from . import ownership
from .ownership import RECORD_PROBLEM, RecordError, device_key

LOG = logging.getLogger("maestrod")

WIRELESS_DEVICE_STATUS = 0x1D4B
BUTTON_CIDS = {
    "middle": (0x0052,),
    "back": (0x0053, 0x0054, 0x00BD, 0x00CE),
    "forward": (0x0056, 0x0057, 0x00CF),
    "gesture": (0x00C3, 0x00D0, 0x00D7),
    "mode_shift": (0x00C4,),
}


IDENTITY_PROBLEM = (
    "Maestro could not confirm this mouse's identity, so it won't change its settings. "
    "Reconnect it."
)


class IdentityChanged(hidpp.NoResponse):
    """An identity read succeeded and the original endpoint is no longer there."""


class Unidentified(hidpp.NoResponse):
    """The mouse's unit ID could not be read, so nothing may be written to it."""


class UnitGate:
    """The single check every HID++ write to a session's mouse passes through.

    Installed as the device's ``write_guard`` (see ``hidpp.check_write``), so
    any write path, including a new one, is covered. Immediately before every
    write, including each retry, it reads the mouse's live unit ID and
    requires the tag recorded when the mouse was opened. A mouse whose unit
    ID cannot be read is read-only.

    Inside ``batch()`` a refusal is final: once one check fails or times out,
    every later write in that batch is refused without being sent.
    """

    def __init__(self, expected):
        self.expected = expected
        self.depth = 0
        self.refused = None

    def __call__(self, device, feature=None, function=None):
        self.check(device)

    def check(self, device):
        """Read the live unit ID and compare it. Writes nothing."""
        if self.depth and self.refused is not None:
            raise type(self.refused)(str(self.refused))
        try:
            return self._check(device)
        except (IdentityChanged, Unidentified) as exc:
            if self.depth:
                self.refused = exc
            raise

    def _check(self, device):
        live = None if self.expected is None else ownership.selector_tag(device_key(device))
        if live is None:
            raise Unidentified(
                "could not read the mouse's unit ID to confirm which mouse this is; "
                "nothing was changed"
            )
        if live != self.expected:
            raise IdentityChanged("a different mouse now answers at this position")
        return live

    @contextmanager
    def batch(self):
        self.depth += 1
        try:
            yield self
        finally:
            self.depth -= 1
            if not self.depth:
                self.refused = None


def guard_device(device):
    """Read the unit ID now and install a UnitGate on ``device``. Returns the gate.

    The gate's ``expected`` is None when the unit ID cannot be read; every
    write is then refused.
    """
    gate = UnitGate(ownership.selector_tag(device_key(device)))
    device.write_guard = gate
    return gate


@contextmanager
def write_batch(device):
    """Group writes to one mouse: each is still checked, and one refusal stops the rest."""
    gate = getattr(device, "write_guard", None)
    if isinstance(gate, UnitGate):
        with gate.batch():
            yield
    else:
        yield


class ControlBusy(RuntimeError):
    """Another app holds a control, or an earlier Maestro run left it taken."""

    def __init__(self, label, detail, leftover=False):
        super().__init__(detail)
        self.label = label
        self.leftover = leftover

    @property
    def status(self):
        if self.leftover:
            return (
                f"Maestro may have left the {self.label} taken during an unexpected shutdown. "
                "Choose Release button to fix it."
            )
        return (
            f"The {self.label} is held by another app (Solaar or logiops?). "
            "Close it, or turn the mouse off and on. If no other app is running, "
            "choose Release button in Maestro settings."
        )


class RecordFailed(RuntimeError):
    """Diversion refused because its ownership record could not be saved."""

    status = RECORD_PROBLEM


def control_label(cid):
    for name in ("gesture", "mode_shift", "middle", "back", "forward"):
        if cid in BUTTON_CIDS[name]:
            return {
                "gesture": "gesture button",
                "mode_shift": "wheel mode button",
                "middle": "middle button",
                "back": "back button",
                "forward": "forward button",
            }[name]
    return f"control {cid:#06x}"


def supported_device(device):
    """Trust only identity established by hidpp.scan_devices(), never a system name."""
    model = getattr(device, "model", None)
    kind = getattr(device, "kind", None)
    return model is not None and (
        kind == "mouse" or (kind == "trackball" and model in ("MX Ergo", "MX Ergo S"))
    )


def same_endpoint(device):
    """Recheck the core's receiver identity before addressing a remembered slot."""
    if not supported_device(device) or not device.writable:
        return False
    if device.node.is_receiver:
        pair = device.channel.pairing_info(device.index, device.node.connection)
        return pair is not None and pair.kind == device.kind and pair.wpid == device.wpid
    # An open fd remains tied to the original Bluetooth device. Verify the
    # current path has the same bus/product identity before using that fd.
    return any(
        node.path == device.node.path
        and node.bus == device.node.bus
        and node.vendor == device.node.vendor
        and node.product == device.node.product
        for node in hidpp.find_hidpp_nodes()
    )


def is_notification(packet):
    return (
        len(packet) >= 4
        and packet[0] in (hidpp.SHORT_REPORT, hidpp.LONG_REPORT)
        and (
            (packet[0] == hidpp.SHORT_REPORT and packet[2] == 0x41)
            or (packet[2] not in (0x8F, 0xFF) and packet[3] & 0x0F == 0)
        )
    )


class EventChannel(hidpp.Channel):
    """Preserve async reports during ordinary Device.call(), including _drain()."""

    @classmethod
    def take(cls, original):
        if isinstance(original, cls):
            return original
        self = cls.__new__(cls)
        self.path, self.fd = original.path, original.fd
        self._swid = getattr(original, "_swid", 0)
        self.notifications = deque()
        self.overflow = False
        original.fd = -1  # ownership transfer; no second reader of the fd
        return self

    def _capture(self, data):
        if is_notification(data):
            if len(self.notifications) >= 4096:
                # A lost release could leave a virtual key down. Fail closed.
                self.overflow = True
            else:
                self.notifications.append(data)

    def _read(self, deadline):
        data = super()._read(deadline)
        if data:
            self._capture(data)
        return data

    def read_events(self):
        self._drain()
        if self.overflow:
            raise OSError("HID++ notification queue overflow; stopping to release controls")
        events = list(self.notifications)
        self.notifications.clear()
        return events


def adopt_channels(devices):
    channels = {}
    for device in devices:
        key = id(device.channel)
        if key not in channels:
            channels[key] = EventChannel.take(device.channel)
        device.channel = channels[key]


def assert_mouse(device):
    if not supported_device(device):
        raise ValueError("refusing diversion without a core-verified supported MX mouse model")
    return device.name()


@dataclass(frozen=True)
class Control:
    cid: int
    flags: int

    @property
    def divertable(self):
        return bool(self.flags & 0x20)

    @property
    def raw_xy(self):
        return bool(self.flags & 0x100)


class Diversion:
    def __init__(self, device, guard=None, ledger=None):
        self.name = assert_mouse(device)
        # Every write is checked against the unit ID read here (UnitGate).
        # Without a readable unit ID the mouse is read-only and nothing is
        # recorded. Nothing is ever reclaimed automatically either way.
        key = device_key(device)
        self.gate = UnitGate(ownership.selector_tag(key))
        self.device = device
        self.guard = guard
        self.ledger = ledger
        self.key = key if ledger is not None else None
        self.controls = {}
        self.owned = {}  # cid -> raw XY requested; record BEFORE a write can time out
        self.flags = {}  # cid -> reporting flags Maestro expects while it owns the control
        self.thumb_owned = False
        self.thumb_flags = None
        # Recorded diversions an earlier run left behind. They stay in the
        # record and block use until the user releases them explicitly.
        self.leftovers = {}  # cid or "thumb" -> recorded (raw_xy, flags) or mode byte
        self.record_pending = False
        if device.has(hidpp.REPROG_CONTROLS_V4):
            count = device.call(hidpp.REPROG_CONTROLS_V4, 0)[0]
            for i in range(count):
                data = device.call(hidpp.REPROG_CONTROLS_V4, 1, bytes([i]))
                cid = int.from_bytes(data[:2], "big")
                self.controls[cid] = Control(cid, data[4] | data[8] << 8)

    @property
    def device(self):
        return self._device

    @device.setter
    def device(self, device):
        # Whatever Device object reaches this mouse carries the session's gate.
        self._device = device
        device.write_guard = self.gate

    @property
    def unit_key(self):
        """Pseudonymous tag of this physical mouse (see ownership.selector_tag), or None."""
        return self.gate.expected

    def verify_unit(self, expected=None, *, required=False):
        """Read the unit ID from the mouse again and confirm it is the same mouse.

        ``unit_key`` is cached when the mouse is first opened, so a same-model
        mouse paired into the same receiver slot would still match it. This
        reads the live unit ID instead. ``required`` (an explicit release
        chosen by selector) also demands it equals ``expected``. Writes
        nothing. Raises IdentityChanged for a different mouse and Unidentified
        when the ID cannot be read.
        """
        live = self.gate.check(self.device)
        if required and live != expected:
            raise IdentityChanged("a different mouse now answers at this position")
        return live

    def cid(self, name):
        return next((cid for cid in BUTTON_CIDS[name] if cid in self.controls), None)

    def reporting(self, cid):
        data = self.device.call(hidpp.REPROG_CONTROLS_V4, 2, cid.to_bytes(2, "big"))
        if int.from_bytes(data[:2], "big") != cid:
            raise hidpp.HidppError("getCidReporting returned a different control ID")
        return data[2]

    def _set(self, cid, enabled, raw_xy):
        """Write only the temporary diversion bits; returns the read-back flags."""
        self.check_endpoint()
        # Each setting has a value bit and a validity bit; remap=0 preserves mapping.
        flags = 0x02 | (0x01 if enabled else 0)
        if raw_xy:
            flags |= 0x20 | (0x10 if enabled else 0)
        self.device.call(hidpp.REPROG_CONTROLS_V4, 3, struct.pack("!HBH", cid, flags, 0))
        expected = (1 if enabled else 0) | (0x10 if enabled and raw_xy else 0)
        mask = 0x11 if raw_xy else 1
        actual = self.reporting(cid)
        if actual & mask != expected:
            raise hidpp.HidppError(f"diversion readback failed for control {cid:#06x}")
        return actual

    def enable(self, cid, raw_xy=False):
        self.check_endpoint()
        control = self.controls[cid]
        if not control.divertable or raw_xy and not control.raw_xy:
            raise ValueError(f"control {cid:#06x} does not support requested diversion")
        if cid in self.owned and self.owned[cid] == raw_xy:
            return
        if cid in self.owned:
            self.disable(cid)
        current = self.reporting(cid)
        if current & 0x15:
            raise ControlBusy(
                control_label(cid),
                f"control {cid:#06x} is already diverted; stop its other owner first",
                leftover=cid in self.leftovers,
            )
        self.leftovers.pop(cid, None)
        self.owned[cid] = raw_xy
        self.flags[cid] = (current & ~0x11) | 0x01 | (0x10 if raw_xy else 0)
        try:
            self._record(required=True)
        except RecordFailed:
            del self.owned[cid], self.flags[cid]
            raise
        self.reassert(cid)

    def reassert(self, cid):
        """Set an owned diversion again and keep the recorded flags in step."""
        actual = self._set(cid, True, self.owned[cid])
        if self.flags.get(cid) != actual:
            self.flags[cid] = actual
            self._record()

    def disable(self, cid):
        if cid in self.owned:
            self._set(cid, False, self.owned[cid])
            del self.owned[cid]
            self.flags.pop(cid, None)
            self._record()

    def _record(self, required=False):
        """Save owned and left-behind diversions. Required saves raise RecordFailed.

        A failed cleanup save is logged and retried later (``retry_record``);
        a stale entry never causes a write, it only shapes the next run's message.
        """
        if self.ledger is None or self.key is None:
            return
        controls = {cid: (raw, self.flags.get(cid, 0x01)) for cid, raw in self.owned.items()}
        thumb = self.thumb_flags if self.thumb_owned else None
        for cid, value in self.leftovers.items():
            if cid == "thumb":
                thumb = value if thumb is None else thumb
            else:
                controls.setdefault(cid, value)
        try:
            self.ledger.update(self.key, controls, thumb)
        except RecordError as exc:
            self.record_pending = True
            LOG.warning("%s: %s", self.name, exc)
            if required:
                raise RecordFailed(str(exc)) from exc
        else:
            self.record_pending = False

    def retry_record(self):
        if self.record_pending:
            self._record()

    def check_leftovers(self):
        """Find diversions an earlier Maestro run left on this same mouse. Writes nothing.

        A normal shutdown already releases every control, so a recorded
        control that is still diverted can only follow a crash or a sudden
        power loss. Matching flags cannot prove who holds it now (another app
        may divert it the same way), so nothing is ever reclaimed
        automatically. A control whose record matches is reported as left
        behind by Maestro and stays recorded until the user chooses Release
        button; anything else is reported as held by another app. Returns the
        plain names of the controls left behind.
        """
        before = set(self.leftovers)
        self.leftovers.clear()
        if self.ledger is None or self.key is None:
            return []
        entry = self.ledger.get(self.key)
        if not entry:
            return []
        self.check_endpoint()
        for cid, (raw_xy, flags) in entry["controls"].items():
            if cid in self.owned or cid not in self.controls:
                continue
            if self.reporting(cid) == flags and flags & 0x11:
                self.leftovers[cid] = (raw_xy, flags)
        thumb = entry["thumb"]
        if thumb is not None and not self.thumb_owned and self.device.has(hidpp.THUMB_WHEEL):
            mode = self.device.call(hidpp.THUMB_WHEEL, 1)[0]
            if mode == thumb and mode & 1:
                self.leftovers["thumb"] = thumb
        # Keep only what this run owns or what Maestro evidently left behind.
        self._record()
        found = [control_label(c) if c != "thumb" else "thumb wheel" for c in self.leftovers]
        if found and set(self.leftovers) != before:
            LOG.warning(
                "%s: %s still taken after an unexpected shutdown; waiting for Release button",
                self.name,
                ", ".join(found),
            )
        return found

    def _release_thumb(self, data):
        self.device.call(hidpp.THUMB_WHEEL, 2, bytes([data[0] & ~1, data[1]]))
        actual = self.device.call(hidpp.THUMB_WHEEL, 1)
        if actual[0] & 1 or actual[1] != data[1]:
            raise hidpp.HidppError("thumb-wheel release readback failed")

    def release_leftovers(self, expected=None, *, required=False):
        """Explicit recovery: undivert controls Maestro may have left behind.

        Covers every control Maestro can divert that this run does not own,
        plus the thumb wheel, whoever diverted it. Only temporary diversion
        bits are cleared. The mouse's live unit ID is checked first (see
        ``verify_unit``), so a replaced or unreadable mouse gets no write.
        Returns the plain names of what was released.
        """
        with self.gate.batch():
            return self._release_leftovers(expected, required)

    def _release_leftovers(self, expected, required):
        self.check_endpoint()
        self.verify_unit(expected, required=required)
        released = []
        for cids in BUTTON_CIDS.values():
            for cid in cids:
                if cid not in self.controls or cid in self.owned:
                    continue
                current = self.reporting(cid)
                if current & 0x11:
                    self._set(cid, False, bool(current & 0x10))
                    released.append(control_label(cid))
                self.leftovers.pop(cid, None)
        if not self.thumb_owned and self.device.has(hidpp.THUMB_WHEEL):
            data = self.device.call(hidpp.THUMB_WHEEL, 1)
            if data[0] & 1:
                self._release_thumb(data)
                released.append("thumb wheel")
            self.leftovers.pop("thumb", None)
        self.leftovers.clear()
        self._record()
        if released:
            LOG.info("%s: released %s on request", self.name, ", ".join(released))
        return released

    def thumb(self, enabled):
        if not enabled and not self.thumb_owned:
            return
        self.check_endpoint()
        if not self.device.has(hidpp.THUMB_WHEEL):
            if enabled:
                raise ValueError("this mouse has no thumb wheel")
            return
        data = self.device.call(hidpp.THUMB_WHEEL, 1)
        if enabled and not self.thumb_owned and data[0] & 1:
            raise ControlBusy(
                "thumb wheel",
                "thumb wheel is already diverted; stop its other owner first",
                leftover="thumb" in self.leftovers,
            )
        # Keep direction and every unowned bit unchanged.
        mode = (data[0] | 1) if enabled else (data[0] & ~1)
        if not self.thumb_owned:
            self.leftovers.pop("thumb", None)
            self.thumb_owned = True  # a lost acknowledgement still needs cleanup
            self.thumb_flags = mode
            try:
                self._record(required=True)
            except RecordFailed:
                self.thumb_owned, self.thumb_flags = False, None
                raise
        self.device.call(hidpp.THUMB_WHEEL, 2, bytes([mode, data[1]]))
        actual = self.device.call(hidpp.THUMB_WHEEL, 1)
        if bool(actual[0] & 1) != enabled or actual[1] != data[1]:
            raise hidpp.HidppError("thumb-wheel diversion readback failed")
        if enabled and self.thumb_flags != actual[0]:
            self.thumb_flags = actual[0]
            self._record()
        if self.thumb_owned != enabled:
            self.thumb_owned = enabled
            self.thumb_flags = None
            self._record()

    def check_endpoint(self, *, write=True):
        if not supported_device(self.device):
            raise IdentityChanged("endpoint is no longer a supported MX mouse")
        if write and not getattr(self.device, "writable", False):
            raise ValueError("mouse identity could not be verified; writes are disabled")
        if self.guard is not None and (write or self.device.writable) and not self.guard():
            raise IdentityChanged(
                "the endpoint is no longer identified as an MX mouse; refusing HID++ writes"
            )

    def close(self):
        """Undo this run's diversions. Each write still passes the unit gate."""
        with self.gate.batch():
            return self._close()

    def _close(self):
        # A refused identity check stops cleanup at once (no further writes);
        # the caller keeps this mouse's record.
        errors = []
        for cid in list(self.owned):
            try:
                self.disable(cid)
            except (IdentityChanged, Unidentified):
                raise
            except Exception as exc:
                errors.append(f"control {cid:#06x}: {exc}")
        try:
            self.thumb(False)
        except (IdentityChanged, Unidentified):
            raise
        except Exception as exc:
            errors.append(f"thumb wheel: {exc}")
        return errors


def decode(packet, device, indexes):
    """Only notifications addressed to this already-identified mouse are decoded."""
    if not is_notification(packet):
        return None
    bluetooth_alias = (
        packet[1] == 0
        and device.index == hidpp.DIRECT_INDEX
        and device.node.connection == "bluetooth"
        and supported_device(device)
        and device.writable
    )
    if packet[1] != device.index and not bluetooth_alias:
        return None
    feature, address, data = packet[2], packet[3], packet[4:]
    if feature == 0x41 and packet[0] == hidpp.SHORT_REPORT:
        # HID++ 1.0 device connection: bit 6 set means link NOT established.
        if not data:
            return None
        return ("disconnected" if data[0] & 0x40 else "reconnect", None)
    if feature == indexes.get(hidpp.REPROG_CONTROLS_V4):
        if address == 0 and len(data) >= 8:
            return "buttons", set(c for c in struct.unpack("!4H", data[:8]) if c)
        if address == 0x10 and len(data) >= 4:
            return "move", struct.unpack("!hh", data[:4])
    if feature == indexes.get(hidpp.THUMB_WHEEL) and address == 0 and len(data) >= 5:
        return "thumb", (int.from_bytes(data[:2], "big", signed=True), data[4] <= 1)
    if (
        feature == indexes.get(WIRELESS_DEVICE_STATUS)
        and address == 0
        and len(data) >= 2
        and data[1] == 1
    ):
        return "reconnect", None
    return None
