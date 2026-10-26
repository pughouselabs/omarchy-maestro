"""Small protocol fake shared by daemon tests, with real reporting flag semantics."""

import struct
from types import SimpleNamespace

from maestro import devices, hidpp


class FakeOutput:
    def __init__(self):
        self.events = []
        self.held = {}
        self.closed = False

    def press(self, code):
        self.held[code] = self.held.get(code, 0) + 1
        self.events.append(("press", code))

    def release(self, code):
        if self.held.get(code, 0) > 1:
            self.held[code] -= 1
        else:
            self.held.pop(code, None)
        self.events.append(("release", code))

    def chord(self, keys):
        self.events.append(("chord", keys))

    def scroll(self, steps, horizontal=False):
        self.events.append(("scroll", steps, horizontal))

    def close(self):
        self.closed = True
        self.held.clear()


class FakeDevice:
    def __init__(self, name="MX Master 2S", kind=3, *, writable=True):
        self._name = name
        self.kind = {0: "keyboard", 3: "mouse", 5: "trackball"}.get(kind, kind)
        self.model = devices.model_for(name) if self.kind in ("mouse", "trackball") else None
        self.writable = writable
        self.wpid = 0x4069 if self.model == "MX Master 2S" else None
        self.calls = []
        self.index = 1
        self.node = hidpp.HidrawNode("/dev/fake", 3, 0x46D, 0xC52B, "receiver")
        self.channel = SimpleNamespace(path="/dev/fake", fd=-1, close=lambda: None)
        self.controls = {0x52: 0x21, 0x53: 0x21, 0x56: 0x21, 0xC3: 0x121, 0xC4: 0x21}
        self.reporting = {cid: 0 for cid in self.controls}
        self.thumb_mode = [0, 1]
        self.fail_enable = False
        self.features = {
            hidpp.DEVICE_NAME: 1,
            hidpp.REPROG_CONTROLS_V4: 2,
            hidpp.THUMB_WHEEL: 3,
            0x1D4B: 4,
            hidpp.ADJUSTABLE_DPI: 5,
            hidpp.SMART_SHIFT: 6,
            hidpp.HIRES_WHEEL: 7,
            hidpp.FW_VERSION: 8,
        }
        self.unit = b"\x8a\x1b\x2c\x3d"  # HID++ 0x0003 unit ID
        self.dpi = 1000
        self.smartshift = [2, 16]
        self.wheel_flags = 2
        self.write_guard = None
        # Another FakeDevice that now answers at this one's address (a mouse
        # paired into the same receiver slot). The write guard still runs here.
        self.route = None

    def name(self):
        return self._name

    def has(self, feature):
        return feature in self.features

    def feature_index(self, feature):
        return self.features.get(feature)

    def ping(self, timeout=0.6):
        return 4, 5

    def call(self, feature, function, params=b"", timeout=1.0):
        # Same contract as hidpp.Device.call: the guard runs before any write.
        hidpp.check_write(self, feature, function)
        if self.route is not None:
            return self.route.answer(feature, function, params)
        return self.answer(feature, function, params)

    def answer(self, feature, function, params=b""):
        self.calls.append((feature, function, params))
        if feature == hidpp.DEVICE_NAME and function == 2:
            data = bytes([{"keyboard": 0, "mouse": 3, "trackball": 5}[self.kind]])
        elif feature == hidpp.REPROG_CONTROLS_V4:
            if function == 0:
                data = bytes([len(self.controls)])
            elif function == 1:
                cid = list(self.controls)[params[0]]
                flags = self.controls[cid]
                data = struct.pack("!HHBBBBB", cid, 0, flags & 255, 0, 0, 0, flags >> 8)
            elif function == 2:
                cid = int.from_bytes(params[:2], "big")
                data = struct.pack("!HBH", cid, self.reporting[cid], cid)
            elif function == 3:
                cid, flags, remap = struct.unpack("!HBH", params)
                assert remap == 0
                assert flags & 0x0C == 0, "persistent diversion must never be touched"
                for bit in (1, 0x10):
                    if flags & bit << 1:
                        self.reporting[cid] = (
                            (self.reporting[cid] | bit)
                            if flags & bit
                            else (self.reporting[cid] & ~bit)
                        )
                if self.fail_enable and flags & 1:
                    self.fail_enable = False
                    raise hidpp.Timeout("lost acknowledgement")
                data = params
        elif feature == hidpp.FW_VERSION and function == 0:
            # entity count, unit ID, transport, model ID
            data = bytes([1]) + self.unit + b"\x00\x0e" + b"\x40\x69\x00\x00\x00\x00"
        elif feature == hidpp.THUMB_WHEEL:
            if function == 2:
                self.thumb_mode[:] = params[:2]
            data = bytes(self.thumb_mode)
        elif feature == hidpp.ADJUSTABLE_DPI:
            if function == 1:
                data = b"\0" + struct.pack("!4H", 200, 0xE032, 4000, 0)
            else:
                if function == 3:
                    self.dpi = int.from_bytes(params[1:3], "big")
                data = b"\0" + struct.pack("!HH", self.dpi, 1000)
        elif feature == hidpp.SMART_SHIFT:
            if function == 1:
                for i, value in enumerate(params[:2]):
                    if value:
                        self.smartshift[i] = value
            data = bytes(self.smartshift)
        elif feature == hidpp.HIRES_WHEEL:
            if function == 2:
                self.wheel_flags = params[0]
            data = bytes([self.wheel_flags])
        else:
            raise AssertionError(f"unexpected feature {feature:#x}, function {function}")
        return data.ljust(16, b"\0")


def packet(feature, address, payload, index=1, short=False):
    return (bytes([0x10 if short else 0x11, index, feature, address]) + payload).ljust(
        7 if short else 20, b"\0"
    )
