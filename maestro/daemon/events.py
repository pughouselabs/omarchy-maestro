"""HID++ event capture and reversible, mouse-only diversion."""

from __future__ import annotations

import os
import struct
from collections import deque
from dataclasses import dataclass

from maestro import hidpp

WIRELESS_DEVICE_STATUS = 0x1D4B
BUTTON_CIDS = {
    "middle": (0x0052,),
    "back": (0x0053, 0x0054, 0x00BD, 0x00CE),
    "forward": (0x0056, 0x0057, 0x00CF),
    "gesture": (0x00C3, 0x00D0, 0x00D7),
    "mode_shift": (0x00C4,),
}


class IdentityChanged(hidpp.NoResponse):
    """An identity read succeeded and the original endpoint is no longer there."""


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

    def _drain(self):
        for _ in range(8192):
            try:
                data = os.read(self.fd, 64)
            except BlockingIOError:
                return
            if not data:
                raise OSError("hidraw channel closed")
            self._capture(data)
        raise OSError("hidraw stream did not drain")

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
    def __init__(self, device, guard=None):
        self.device = device
        self.guard = guard
        self.name = assert_mouse(device)
        self.controls = {}
        self.owned = {}  # cid -> raw XY requested; record BEFORE a write can time out
        self.thumb_owned = False
        if device.has(hidpp.REPROG_CONTROLS_V4):
            count = device.call(hidpp.REPROG_CONTROLS_V4, 0)[0]
            for i in range(count):
                data = device.call(hidpp.REPROG_CONTROLS_V4, 1, bytes([i]))
                cid = int.from_bytes(data[:2], "big")
                self.controls[cid] = Control(cid, data[4] | data[8] << 8)

    def cid(self, name):
        return next((cid for cid in BUTTON_CIDS[name] if cid in self.controls), None)

    def reporting(self, cid):
        data = self.device.call(hidpp.REPROG_CONTROLS_V4, 2, cid.to_bytes(2, "big"))
        if int.from_bytes(data[:2], "big") != cid:
            raise hidpp.HidppError("getCidReporting returned a different control ID")
        return data[2]

    def _set(self, cid, enabled, raw_xy):
        self.check_endpoint()
        # Each setting has a value bit and a validity bit; remap=0 preserves mapping.
        flags = 0x02 | (0x01 if enabled else 0)
        if raw_xy:
            flags |= 0x20 | (0x10 if enabled else 0)
        self.device.call(hidpp.REPROG_CONTROLS_V4, 3, struct.pack("!HBH", cid, flags, 0))
        expected = (1 if enabled else 0) | (0x10 if enabled and raw_xy else 0)
        mask = 0x11 if raw_xy else 1
        if self.reporting(cid) & mask != expected:
            raise hidpp.HidppError(f"diversion readback failed for control {cid:#06x}")

    def enable(self, cid, raw_xy=False):
        self.check_endpoint()
        control = self.controls[cid]
        if not control.divertable or raw_xy and not control.raw_xy:
            raise ValueError(f"control {cid:#06x} does not support requested diversion")
        if cid in self.owned and self.owned[cid] == raw_xy:
            return
        if cid in self.owned:
            self.disable(cid)
        if self.reporting(cid) & 0x15:
            raise RuntimeError(
                f"control {cid:#06x} is already diverted; stop its other owner first"
            )
        self.owned[cid] = raw_xy
        self._set(cid, True, raw_xy)

    def disable(self, cid):
        if cid in self.owned:
            self._set(cid, False, self.owned[cid])
            del self.owned[cid]

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
            raise RuntimeError("thumb wheel is already diverted; stop its other owner first")
        # Keep direction and every unowned bit unchanged.
        mode = (data[0] | 1) if enabled else (data[0] & ~1)
        self.thumb_owned = True  # a lost acknowledgement still needs cleanup
        self.device.call(hidpp.THUMB_WHEEL, 2, bytes([mode, data[1]]))
        actual = self.device.call(hidpp.THUMB_WHEEL, 1)
        if bool(actual[0] & 1) != enabled or actual[1] != data[1]:
            raise hidpp.HidppError("thumb-wheel diversion readback failed")
        self.thumb_owned = enabled

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
        errors = []
        for cid in list(self.owned):
            try:
                self.disable(cid)
            except Exception as exc:
                errors.append(f"control {cid:#06x}: {exc}")
        try:
            self.thumb(False)
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
