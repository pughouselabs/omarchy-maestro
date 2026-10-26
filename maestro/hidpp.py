"""Minimal HID++ 2.0 client for Logitech mice, standard library only.

HID++ messages travel over a hidraw node: either a receiver (Unifying or
Bolt), where each paired device has an index 1-6, or the device itself
over Bluetooth/USB, addressed as index 0xFF.

Every feature is looked up by its 16-bit ID through the ROOT feature, so the
same code works on any model; a model simply lacks the features it doesn't have.
"""

from __future__ import annotations

import errno
import os
import re
import select
import time
from dataclasses import dataclass, field

from . import devices

LOGITECH_VENDOR = 0x046D

SHORT_REPORT = 0x10  # 7 bytes
LONG_REPORT = 0x11  # 20 bytes
SHORT_LEN = 7
LONG_LEN = 20

DIRECT_INDEX = 0xFF
HIDPP10_ERROR = 0x8F
HIDPP20_ERROR = 0xFF

# Feature IDs (HID++ 2.0).
ROOT = 0x0000
FEATURE_SET = 0x0001
FW_VERSION = 0x0003
DEVICE_NAME = 0x0005
BATTERY_STATUS = 0x1000
UNIFIED_BATTERY = 0x1004
CHANGE_HOST = 0x1814
REPROG_CONTROLS_V4 = 0x1B04
VERTICAL_SCROLLING = 0x2100
SMART_SHIFT = 0x2110
SMART_SHIFT_ENHANCED = 0x2111
HIRES_WHEEL = 0x2121
THUMB_WHEEL = 0x2150
ADJUSTABLE_DPI = 0x2201
EXTENDED_ADJUSTABLE_DPI = 0x2202
GESTURE_2 = 0x6501

UNIFYING_PRODUCTS = {0xC52B, 0xC532}
BOLT_PRODUCTS = {0xC548}
RECEIVER_PRODUCTS = UNIFYING_PRODUCTS | BOLT_PRODUCTS

HIDPP20_ERRORS = {
    1: "unknown",
    2: "invalid argument",
    3: "out of range",
    4: "hardware error",
    5: "logitech internal",
    6: "invalid feature index",
    7: "invalid function",
    8: "busy",
    9: "unsupported",
}


class HidppError(Exception):
    """The device answered with an HID++ error."""


class NoResponse(Exception):
    """The device is not reachable (unpaired, switched off, or out of range)."""


class Timeout(NoResponse):
    """Nothing answered in time. A dozing mouse can take a moment to wake."""


@dataclass
class HidrawNode:
    path: str
    bus: int
    vendor: int
    product: int
    name: str

    @property
    def is_receiver(self) -> bool:
        return self.product in RECEIVER_PRODUCTS

    @property
    def connection(self) -> str:
        if self.product in UNIFYING_PRODUCTS:
            return "unifying"
        if self.product in BOLT_PRODUCTS:
            return "bolt"
        return "bluetooth" if self.bus == 0x0005 else "other"


_HID_DEVICE_DIR = re.compile(r"^[0-9A-F]{4}:[0-9A-F]{4}:[0-9A-F]{4}\.[0-9A-F]{4}$")


def _supports_hidpp(descriptor: bytes) -> bool:
    # Vendor usage page 0xFF00 plus long report ID 0x11.
    return b"\x06\x00\xff" in descriptor and b"\x85\x11" in descriptor


def find_hidpp_nodes(sysfs: str = "/sys/class/hidraw") -> list[HidrawNode]:
    """Logitech hidraw nodes that speak HID++, skipping per-device children of a
    receiver (those are reached through the receiver node instead)."""
    nodes = []
    try:
        entries = sorted(os.listdir(sysfs), key=lambda n: int(re.sub(r"\D", "", n) or 0))
    except FileNotFoundError:
        return nodes
    for entry in entries:
        device = os.path.join(sysfs, entry, "device")
        try:
            with open(os.path.join(device, "uevent"), encoding="utf-8") as source:
                uevent = source.read()
            with open(os.path.join(device, "report_descriptor"), "rb") as source:
                descriptor = source.read()
        except OSError:
            continue
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        try:
            bus, vendor, product = (int(x, 16) for x in fields.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if vendor != LOGITECH_VENDOR or not _supports_hidpp(descriptor):
            continue
        # Never probe gaming/Nano receivers or unrelated direct USB devices.
        if product not in RECEIVER_PRODUCTS and bus != 0x0005:
            continue
        parent = os.path.basename(os.path.dirname(os.path.realpath(device)))
        if _HID_DEVICE_DIR.match(parent):
            continue  # paired-device child of a receiver
        nodes.append(HidrawNode(f"/dev/{entry}", bus, vendor, product, fields.get("HID_NAME", "")))
    return nodes


class Channel:
    """One open hidraw node. Not thread-safe; one request at a time."""

    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        self._swid = 0

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self) -> Channel:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _next_swid(self) -> int:
        # Software ID 0 is reserved for device notifications.
        self._swid = self._swid % 15 + 1
        return self._swid

    def _drain(self) -> None:
        while True:
            try:
                os.read(self.fd, 64)
            except BlockingIOError:
                return

    def _read(self, deadline: float) -> bytes | None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        ready, _, _ = select.select([self.fd], [], [], remaining)
        if not ready:
            return None
        try:
            return os.read(self.fd, 64)
        except BlockingIOError:
            return b""
        except OSError as e:
            if e.errno == errno.EAGAIN:
                return b""
            raise

    def request(
        self,
        index: int,
        feature_index: int,
        function: int,
        params: bytes = b"",
        timeout: float = 1.0,
    ) -> bytes:
        """Send one HID++ 2.0 request and return the reply's 16 parameter bytes."""
        if len(params) > LONG_LEN - 4:
            raise ValueError("too many parameters")
        swid = self._next_swid()
        func_byte = ((function & 0x0F) << 4) | swid
        message = bytes([LONG_REPORT, index, feature_index, func_byte]) + params
        message = message.ljust(LONG_LEN, b"\x00")
        try:
            self._drain()
            os.write(self.fd, message)
        except OSError as e:
            raise NoResponse(f"device disconnected on {self.path}: {e.strerror}") from e
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = self._read(deadline)
            except OSError as e:
                raise NoResponse(f"device disconnected on {self.path}: {e.strerror}") from e
            if reply is None:
                raise Timeout(f"no reply from device {index} on {self.path}")
            if len(reply) < 4 or reply[0] not in (SHORT_REPORT, LONG_REPORT):
                continue
            # Some Bluetooth HID++ devices answer direct-index requests as 0x00.
            if reply[1] != index and not (index == DIRECT_INDEX and reply[1] == 0):
                continue
            # HID++ 1.0 error (receiver says the device is not there).
            if len(reply) >= 6 and reply[2] == HIDPP10_ERROR and reply[3] == feature_index:
                raise NoResponse(f"device {index} not reachable (HID++ 1.0 error {reply[5]:#04x})")
            # HID++ 2.0 error.
            if (
                len(reply) >= 6
                and reply[2] == HIDPP20_ERROR
                and reply[3] == feature_index
                and reply[4] == func_byte
            ):
                code = reply[5]
                raise HidppError(HIDPP20_ERRORS.get(code, f"error {code}"))
            if reply[2] == feature_index and reply[3] == func_byte:
                return bytes(reply[4:]).ljust(16, b"\x00")

    def pairing_info(self, slot: int, connection: str, timeout: float = 0.4) -> PairingInfo | None:
        """Read a receiver register only. No request goes to a paired device.

        HID++ 1.0 long-register reads use a *short request* and a long reply.
        Unifying and Bolt use different subregisters and layouts.
        """
        if connection not in ("unifying", "bolt") or not 1 <= slot <= 6:
            raise ValueError("invalid receiver slot or type")
        subregister = (0x20 + slot - 1) if connection == "unifying" else (0x50 + slot)
        message = bytes((SHORT_REPORT, DIRECT_INDEX, 0x83, 0xB5, subregister, 0, 0))
        try:
            self._drain()
            os.write(self.fd, message)
        except OSError as e:
            raise NoResponse(f"receiver disconnected on {self.path}: {e.strerror}") from e
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = self._read(deadline)
            except OSError as e:
                raise NoResponse(f"receiver disconnected on {self.path}: {e.strerror}") from e
            if reply is None:
                raise Timeout(f"receiver did not answer pairing info for slot {slot}")
            if len(reply) < 6 or reply[1] != DIRECT_INDEX:
                continue
            if reply[2] == HIDPP10_ERROR and reply[3:5] == b"\x83\xb5":
                if reply[5] == 0x03:  # empty slot
                    return None
                raise HidppError(f"receiver pairing info for slot {slot}: error {reply[5]:#04x}")
            if reply[2:4] != b"\x83\xb5" or reply[4] != subregister:
                continue
            if connection == "unifying" and len(reply) >= 12:
                return PairingInfo(
                    slot, _receiver_kind(reply[11] & 0x0F), int.from_bytes(reply[7:9], "big")
                )
            if connection == "bolt" and len(reply) >= 8:
                return PairingInfo(
                    slot, _receiver_kind(reply[5] & 0x0F), int.from_bytes(reply[6:8][::-1], "big")
                )
            raise HidppError(f"short pairing info reply for slot {slot}")


def _receiver_kind(code: int) -> str:
    return {1: "keyboard", 2: "mouse", 8: "trackball"}.get(code, "other")


@dataclass(frozen=True)
class PairingInfo:
    slot: int
    kind: str
    wpid: int


@dataclass
class Device:
    """A HID++ 2.0 device reachable through a channel at an index."""

    channel: Channel
    index: int
    node: HidrawNode
    wpid: int | None = None
    kind: str | None = None
    version: tuple[int, int] | None = None
    reported_name: str | None = None
    model: str | None = None
    writable: bool = True
    _features: dict[int, int | None] = field(default_factory=dict)

    def ping(self, timeout: float = 0.6) -> tuple[int, int]:
        """Returns the HID++ protocol version; raises NoResponse if absent."""
        reply = self.channel.request(self.index, 0, 1, b"\x00\x00\x5a", timeout=timeout)
        self.version = (reply[0], reply[1])
        return self.version

    def feature_index(self, feature_id: int) -> int | None:
        if feature_id not in self._features:
            reply = self.call(ROOT, 0, feature_id.to_bytes(2, "big"))
            self._features[feature_id] = reply[0] or None
        return self._features[feature_id]

    def has(self, feature_id: int) -> bool:
        return self.feature_index(feature_id) is not None

    def call(
        self, feature_id: int, function: int, params: bytes = b"", timeout: float = 1.0
    ) -> bytes:
        if feature_id == ROOT:
            idx = 0
        else:
            idx = self.feature_index(feature_id)
            if idx is None:
                raise HidppError(f"feature {feature_id:#06x} not supported")
        return self.channel.request(self.index, idx, function, params, timeout=timeout)

    # ----- identity -------------------------------------------------------

    def name(self) -> str:
        if self.reported_name is not None:
            return self.reported_name
        count = self.call(DEVICE_NAME, 0)[0]
        chars = b""
        while len(chars) < count:
            chunk = self.call(DEVICE_NAME, 1, bytes([len(chars)]))
            if not chunk.strip(b"\x00"):
                raise HidppError("device name reply was empty")
            chars += chunk[: count - len(chars)]
        self.reported_name = chars.decode("utf-8", "replace").strip("\x00 ")
        return self.reported_name

    def device_type(self) -> str | None:
        """DEVICE_NAME.getDeviceType: 0x03 denotes a mouse."""
        if not self.has(DEVICE_NAME):
            return None
        return {0: "keyboard", 3: "mouse", 5: "trackball"}.get(
            self.call(DEVICE_NAME, 2)[0], "other"
        )

    def feature_details(self) -> list[dict]:
        """Feature IDs and versions from FEATURE_SET, with no device identifiers."""
        count = self.call(FEATURE_SET, 0)[0]
        details = [{"id": "0x0000", "version": 0}]
        for index in range(1, count + 1):
            reply = self.call(FEATURE_SET, 1, bytes([index]))
            details.append({"id": f"0x{int.from_bytes(reply[:2], 'big'):04x}", "version": reply[3]})
        return details

    def feature_list(self) -> list[int]:
        """Every feature ID the device reports, in index order."""
        return [int(item["id"], 16) for item in self.feature_details()[1:]]


@dataclass(frozen=True)
class SleepingMouse:
    path: str
    index: int
    connection: str
    wpid: int | None
    name: str | None = None


@dataclass
class ScanResult:
    devices: list[Device] = field(default_factory=list)
    sleeping: list[SleepingMouse] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def scan_devices(nodes: list[HidrawNode] | None = None) -> ScanResult:
    """Discover mice safely, leaving channels open for the returned devices.

    Pairing kind is checked on receivers before any per-device request. Direct
    Bluetooth nodes are gated by sysfs product ID and strict MX-family identity
    before DEVICE_NAME confirms mouse or supported trackball kind.
    """
    result = ScanResult()
    for node in nodes if nodes is not None else find_hidpp_nodes():
        direct_model = None
        if not node.is_receiver:
            if node.connection != "bluetooth":
                continue
            direct_model = devices.bluetooth_model(node.name, node.product)
            if direct_model is None:
                continue
        try:
            channel = Channel(node.path)
        except OSError as e:
            result.errors.append(f"cannot open {node.path}: {e.strerror}")
            continue
        indexes = range(1, 7) if node.is_receiver else [DIRECT_INDEX]
        found = False
        for index in indexes:
            pair = None
            if node.is_receiver:
                try:
                    pair = channel.pairing_info(index, node.connection)
                except (NoResponse, HidppError) as e:
                    result.errors.append(f"{node.path} slot {index}: {e}")
                    continue
                if pair is None or pair.kind not in ("mouse", "trackball"):
                    continue
            device = Device(
                channel,
                index,
                node,
                wpid=pair.wpid if pair else None,
                kind=pair.kind if pair else None,
            )
            try:
                try:
                    major, _ = device.ping()
                except Timeout:
                    # Silence (rather than an error) usually means asleep: give it time to wake.
                    major, _ = device.ping(timeout=2.5)
                if major < 2:
                    continue
                if not node.is_receiver:
                    device.kind = device.device_type()
                    if device.kind not in ("mouse", "trackball"):
                        continue
                name_read = False
                try:
                    device.reported_name = device.name()
                    name_read = True
                except (HidppError, NoResponse):
                    if node.is_receiver:
                        device.reported_name = devices.KNOWN_PRODUCTS.get(
                            device.wpid, "Logitech mouse"
                        )
                    else:
                        device.reported_name = node.name
                if node.is_receiver:
                    device.model = devices.model_for(device.reported_name, device.wpid)
                elif node.product in devices.KNOWN_BT_MICE:
                    device.model = devices.KNOWN_BT_MICE[node.product]
                elif name_read:
                    # A successful HID++ name that is not MX cannot be replaced
                    # by the system name used only to qualify the probe.
                    device.model = devices.bluetooth_model(device.reported_name, node.product)
                else:
                    device.model = direct_model
                    device.writable = False  # unverified system-name fallback
                if device.kind == "trackball" and device.model not in ("MX Ergo", "MX Ergo S"):
                    continue
            except Timeout:
                result.sleeping.append(
                    SleepingMouse(
                        node.path,
                        index,
                        node.connection,
                        device.wpid,
                        node.name if not node.is_receiver else None,
                    )
                )
                continue
            except (NoResponse, HidppError) as e:
                result.errors.append(f"{node.path} device {index}: {e}")
                continue
            result.devices.append(device)
            found = True
        if not found:
            channel.close()
    return result


def open_devices(nodes: list[HidrawNode] | None = None) -> list[Device]:
    """Every reachable mouse, including unsupported Logitech mice."""
    return scan_devices(nodes).devices


def close_devices(devices: list[Device]) -> None:
    for channel in {id(d.channel): d.channel for d in devices}.values():
        channel.close()
