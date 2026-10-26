"""Runtime-discovered settings and read-only capabilities for MX mice."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import devices, hidpp
from .hidpp import Device, HidppError

BATTERY_STATUS_NAMES = {
    0: "discharging",
    1: "charging",
    2: "almost full",
    3: "full",
    4: "charging slowly",
    5: "invalid battery",
    6: "thermal error",
}


def is_supported(name: str, kind: str = "mouse", product_id: int | None = None) -> bool:
    model = devices.model_for(name, product_id)
    return (kind == "mouse" and model is not None) or (
        kind == "trackball" and model in ("MX Ergo", "MX Ergo S")
    )


@dataclass
class Battery:
    percent: int
    status: str
    charging: bool
    source: str = ""


@dataclass
class Dpi:
    current: int
    default: int
    choices: list[int]
    minimum: int
    maximum: int
    step: int | None
    source: str = "0x2201"
    y_current: int | None = None
    y_default: int | None = None
    lod: int | None = None


@dataclass
class SmartShift:
    mode: str  # "ratchet" or "freespin"
    threshold: int  # 1-254: wheel speed that switches to free-spin; 255 = never
    enhanced: bool


@dataclass
class Wheel:
    hires: bool
    inverted: bool
    diverted: bool


@dataclass
class Host:
    current: int  # 1-based Easy-Switch channel
    count: int


@dataclass
class ThumbWheel:
    inverted: bool
    diverted: bool
    resolution: int | None


@dataclass
class Control:
    cid: int
    task_id: int
    divertable: bool
    persistently_divertable: bool
    raw_xy: bool


# ----- battery --------------------------------------------------------------


def battery(dev: Device) -> Battery | None:
    if dev.has(hidpp.UNIFIED_BATTERY):
        r = dev.call(hidpp.UNIFIED_BATTERY, 1)
        status = BATTERY_STATUS_NAMES.get(r[2], "unknown")
        return Battery(r[0], status, r[2] in (1, 2, 4), "0x1004")
    if dev.has(hidpp.BATTERY_STATUS):
        r = dev.call(hidpp.BATTERY_STATUS, 0)
        status = BATTERY_STATUS_NAMES.get(r[2], "unknown")
        return Battery(r[0], status, r[2] in (1, 2, 4), "0x1000")
    return None


# ----- DPI --------------------------------------------------------------------


def parse_dpi_list(data: bytes) -> tuple[list[int], int | None]:
    """Decode a getSensorDpiList payload (after the sensor index byte).

    Values are big-endian 16-bit, terminated by 0. A value whose top three bits
    are set (0xE000) is a step size meaning "every N between the previous and
    the next value"."""
    values = []
    step = None
    i = 0
    raw = []
    while i + 1 < len(data):
        v = int.from_bytes(data[i : i + 2], "big")
        i += 2
        if v == 0:
            break
        raw.append(v)
    j = 0
    while j < len(raw):
        v = raw[j]
        if v >> 13 == 0b111 and values and j + 1 < len(raw):
            step = v & 0x1FFF
            end = raw[j + 1]
            start = values[-1]
            values.extend(range(start + step, end + 1, step))
            if values[-1] != end:
                values.append(end)
            j += 2
            continue
        values.append(v)
        j += 1
    return values, step


def _extended_dpi_choices(dev: Device, direction: int) -> tuple[list[int], int | None]:
    data = b""
    for page in range(32):
        reply = dev.call(hidpp.EXTENDED_ADJUSTABLE_DPI, 2, bytes((0, direction, page)))
        data += reply[3:]
        if b"\x00\x00" in (data[i : i + 2] for i in range(0, len(data) - 1, 2)):
            break
    else:
        raise HidppError("extended DPI list has no terminator")
    return parse_dpi_list(data)


def dpi(dev: Device) -> Dpi | None:
    if dev.has(hidpp.EXTENDED_ADJUSTABLE_DPI):
        info = dev.call(hidpp.EXTENDED_ADJUSTABLE_DPI, 1, b"\x00")
        choices, step = _extended_dpi_choices(dev, 0)
        r = dev.call(hidpp.EXTENDED_ADJUSTABLE_DPI, 5, b"\x00")
        current = int.from_bytes(r[1:3], "big") or int.from_bytes(r[3:5], "big")
        default = int.from_bytes(r[3:5], "big") or current
        if not choices:
            choices = [current]
        y_current = (
            int.from_bytes(r[5:7], "big") or int.from_bytes(r[7:9], "big") if info[2] & 1 else None
        )
        y_default = (int.from_bytes(r[7:9], "big") or y_current) if info[2] & 1 else None
        return Dpi(
            current,
            default,
            choices,
            min(choices),
            max(choices),
            step,
            "0x2202",
            y_current,
            y_default,
            r[9] if info[2] & 2 else None,
        )
    if not dev.has(hidpp.ADJUSTABLE_DPI):
        return None
    listing = dev.call(hidpp.ADJUSTABLE_DPI, 1, b"\x00")
    choices, step = parse_dpi_list(listing[1:])
    r = dev.call(hidpp.ADJUSTABLE_DPI, 2, b"\x00")
    current = int.from_bytes(r[1:3], "big")
    default = int.from_bytes(r[3:5], "big") or current
    if not choices:
        choices = [current]
    return Dpi(current, default, choices, min(choices), max(choices), step)


def set_dpi(dev: Device, value: int) -> int:
    info = dpi(dev)
    if info is None:
        raise HidppError("this mouse has no adjustable DPI")
    if value not in info.choices:
        nearest = min(info.choices, key=lambda c: abs(c - value))
        raise ValueError(f"{value} DPI is not available on this mouse (nearest: {nearest})")
    if info.source == "0x2202":
        # The extended feature can also carry Y DPI and lift-off distance.
        # Preserve both instead of silently resetting them when changing X.
        params = b"\x00" + value.to_bytes(2, "big")
        params += (info.y_current or 0).to_bytes(2, "big")
        params += bytes((info.lod or 0,))
        dev.call(hidpp.EXTENDED_ADJUSTABLE_DPI, 6, params)
    else:
        dev.call(hidpp.ADJUSTABLE_DPI, 3, b"\x00" + value.to_bytes(2, "big"))
    return dpi(dev).current


# ----- SmartShift -------------------------------------------------------------


def smartshift(dev: Device) -> SmartShift | None:
    if dev.has(hidpp.SMART_SHIFT_ENHANCED):
        r = dev.call(hidpp.SMART_SHIFT_ENHANCED, 1)
        enhanced = True
    elif dev.has(hidpp.SMART_SHIFT):
        r = dev.call(hidpp.SMART_SHIFT, 0)
        enhanced = False
    else:
        return None
    mode = "freespin" if r[0] == 1 else "ratchet"
    return SmartShift(mode, r[1], enhanced)


def set_smartshift(
    dev: Device, mode: str | None = None, threshold: int | None = None
) -> SmartShift:
    """Change free-spin/ratchet mode and/or the auto-switch threshold (1-255).
    A value left as None is not changed (the protocol uses 0 for "keep")."""
    if mode not in (None, "ratchet", "freespin"):
        raise ValueError("mode must be 'ratchet' or 'freespin'")
    if threshold is not None and not 1 <= threshold <= 255:
        raise ValueError("threshold must be 1-255")
    mode_byte = {None: 0, "freespin": 1, "ratchet": 2}[mode]
    params = bytes([mode_byte, threshold or 0])
    if dev.has(hidpp.SMART_SHIFT_ENHANCED):
        dev.call(hidpp.SMART_SHIFT_ENHANCED, 2, params)
    elif dev.has(hidpp.SMART_SHIFT):
        dev.call(hidpp.SMART_SHIFT, 1, params)
    else:
        raise HidppError("this mouse has no SmartShift")
    return smartshift(dev)


# ----- scroll wheel -----------------------------------------------------------


def wheel(dev: Device) -> Wheel | None:
    if not dev.has(hidpp.HIRES_WHEEL):
        return None
    flags = dev.call(hidpp.HIRES_WHEEL, 1)[0]
    return Wheel(hires=bool(flags & 0x02), inverted=bool(flags & 0x04), diverted=bool(flags & 0x01))


def set_wheel(dev: Device, inverted: bool | None = None) -> Wheel:
    """Change scroll direction while preserving every other wheel mode bit."""
    if not dev.has(hidpp.HIRES_WHEEL):
        raise HidppError("this mouse has no hi-res wheel")
    flags = dev.call(hidpp.HIRES_WHEEL, 1)[0]
    # The Linux driver owns hi-res mode and its scroll multiplier; leave it alone.
    if inverted is not None:
        flags = (flags | 0x04) if inverted else (flags & ~0x04)
        dev.call(hidpp.HIRES_WHEEL, 2, bytes([flags]))
    return wheel(dev)


def thumb_wheel(dev: Device) -> ThumbWheel | None:
    if not dev.has(hidpp.THUMB_WHEEL):
        return None
    info = dev.call(hidpp.THUMB_WHEEL, 0)
    config = dev.call(hidpp.THUMB_WHEEL, 1)
    # getInfo's native-resolution field is the 16-bit value after capabilities.
    resolution = int.from_bytes(info[1:3], "big") or None
    return ThumbWheel(
        inverted=bool(config[1] & 1), diverted=bool(config[0] & 1), resolution=resolution
    )


def parse_control(data: bytes) -> Control:
    """Decode REPROG_CONTROLS_V4.getCidInfo without reading mapping state."""
    if len(data) < 9:
        raise ValueError("short control information")
    flags = data[4] | (data[8] << 8)
    return Control(
        int.from_bytes(data[:2], "big"),
        int.from_bytes(data[2:4], "big"),
        bool(flags & 0x20),
        bool(flags & 0x40),
        bool(flags & 0x100),
    )


def controls(dev: Device) -> list[Control] | None:
    if not dev.has(hidpp.REPROG_CONTROLS_V4):
        return None
    count = dev.call(hidpp.REPROG_CONTROLS_V4, 0)[0]
    return [parse_control(dev.call(hidpp.REPROG_CONTROLS_V4, 1, bytes((i,)))) for i in range(count)]


# ----- Easy-Switch ------------------------------------------------------------


def host(dev: Device) -> Host | None:
    if not dev.has(hidpp.CHANGE_HOST):
        return None
    r = dev.call(hidpp.CHANGE_HOST, 0)
    return Host(current=r[1] + 1, count=r[0])


# ----- everything -------------------------------------------------------------


def status(dev: Device) -> dict:
    """Snapshot of every supported setting, as plain JSON-ready data."""
    model = getattr(dev, "model", None) or devices.model_for(dev.name(), getattr(dev, "wpid", None))
    kind = getattr(dev, "kind", "mouse")
    supported = model is not None and (
        kind == "mouse" or (kind == "trackball" and model in ("MX Ergo", "MX Ergo S"))
    )
    out: dict = {
        "name": dev.name(),
        "path": dev.node.path,
        "index": dev.index,
        "receiver": dev.node.is_receiver,
        "connection": dev.node.connection,
        "wpid": f"{dev.wpid:04X}" if getattr(dev, "wpid", None) is not None else None,
        "model": model,
        "supported": supported,
    }
    if not out["supported"]:
        return out
    for key, reader in (
        ("battery", battery),
        ("dpi", dpi),
        ("smartshift", smartshift),
        ("wheel", wheel),
        ("thumb_wheel", thumb_wheel),
        ("host", host),
    ):
        try:
            value = reader(dev)
        except (HidppError, hidpp.NoResponse) as e:
            out[key] = {"error": str(e)}
            continue
        out[key] = asdict(value) if value is not None else None
    return out


def diagnose(dev: Device) -> dict:
    """A whitelist of shareable facts. Never include raw FW_VERSION replies."""
    model = devices.model_for(getattr(dev, "model", None) or "", getattr(dev, "wpid", None))
    if model is None:
        try:
            reported_name = dev.name()
        except (HidppError, hidpp.NoResponse):
            reported_name = getattr(dev, "reported_name", None) or dev.node.name
        model = devices.model_for(reported_name, getattr(dev, "wpid", None))
        if model is None and not dev.node.is_receiver:
            model = devices.bluetooth_model(reported_name, dev.node.product)
    kind = getattr(dev, "kind", "mouse")
    if kind not in ("mouse", "trackball") or (
        kind == "trackball" and model not in ("MX Ergo", "MX Ergo S")
    ):
        model = None
    out = {
        "name": model or "unsupported Logitech device",
        "model": model,
        "supported": model is not None,
        "connection": dev.node.connection,
        "receiver_product_id": f"{dev.node.product:04X}" if dev.node.is_receiver else None,
        "wpid": f"{dev.wpid:04X}" if dev.wpid is not None else None,
        "product_id": f"{dev.node.product:04X}" if not dev.node.is_receiver else None,
        "hidpp_version": ".".join(map(str, dev.version)) if dev.version else None,
    }
    try:
        out["features"] = dev.feature_details()
    except (HidppError, hidpp.NoResponse) as e:
        out["features"] = None
        out["features_error"] = str(e)
    try:
        out["battery_source"] = (
            "0x1004"
            if dev.has(hidpp.UNIFIED_BATTERY)
            else "0x1000"
            if dev.has(hidpp.BATTERY_STATUS)
            else None
        )
    except (HidppError, hidpp.NoResponse) as e:
        out["battery_source"] = None
        out["battery_error"] = str(e)
    try:
        found = controls(dev)
        out["controls"] = [asdict(c) for c in found] if found is not None else None
    except (HidppError, hidpp.NoResponse) as e:
        out["controls"] = None
        out["controls_error"] = str(e)
    return out


last_scan = hidpp.ScanResult()


def find_mice(include_unsupported: bool = False) -> list[Device]:
    """Open mouse-kind devices, optionally including unknown Logitech mice."""
    global last_scan
    last_scan = hidpp.scan_devices()
    if include_unsupported:
        return last_scan.devices
    mice = [d for d in last_scan.devices if d.model is not None]
    keep = {id(d.channel) for d in mice}
    hidpp.close_devices([d for d in last_scan.devices if id(d.channel) not in keep])
    return mice
