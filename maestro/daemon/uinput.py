"""Small Linux uinput emitter. No evdev dependency and no shell processes."""

from __future__ import annotations

import fcntl
import os
import struct

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
REL_HWHEEL, REL_WHEEL = 6, 8
UI_DEV_CREATE, UI_DEV_DESTROY = 0x5501, 0x5502
UI_DEV_SETUP = 0x405C5503
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
EVENT = struct.Struct("@llHHi")

KEYS = {
    "ESC": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "MINUS": 12,
    "EQUAL": 13,
    "BACKSPACE": 14,
    "TAB": 15,
    "Q": 16,
    "W": 17,
    "E": 18,
    "R": 19,
    "T": 20,
    "Y": 21,
    "U": 22,
    "I": 23,
    "O": 24,
    "P": 25,
    "LEFTBRACE": 26,
    "RIGHTBRACE": 27,
    "ENTER": 28,
    "LEFTCTRL": 29,
    "A": 30,
    "S": 31,
    "D": 32,
    "F": 33,
    "G": 34,
    "H": 35,
    "J": 36,
    "K": 37,
    "L": 38,
    "SEMICOLON": 39,
    "APOSTROPHE": 40,
    "GRAVE": 41,
    "LEFTSHIFT": 42,
    "BACKSLASH": 43,
    "Z": 44,
    "X": 45,
    "C": 46,
    "V": 47,
    "B": 48,
    "N": 49,
    "M": 50,
    "COMMA": 51,
    "DOT": 52,
    "SLASH": 53,
    "RIGHTSHIFT": 54,
    "KPASTERISK": 55,
    "LEFTALT": 56,
    "SPACE": 57,
    "CAPSLOCK": 58,
    **{f"F{i}": 58 + i for i in range(1, 11)},
    "F11": 87,
    "F12": 88,
    "KPENTER": 96,
    "RIGHTCTRL": 97,
    "RIGHTALT": 100,
    "HOME": 102,
    "UP": 103,
    "PAGEUP": 104,
    "LEFT": 105,
    "RIGHT": 106,
    "END": 107,
    "DOWN": 108,
    "PAGEDOWN": 109,
    "INSERT": 110,
    "DELETE": 111,
    "MUTE": 113,
    "MICMUTE": 248,
    "VOLUMEDOWN": 114,
    "VOLUMEUP": 115,
    "LEFTMETA": 125,
    "RIGHTMETA": 126,
    "COMPOSE": 127,
    "PAUSE": 119,
    "PLAYPAUSE": 164,
    "NEXTSONG": 163,
    "PREVIOUSSONG": 165,
    "SYSRQ": 99,
    **{f"F{i}": 183 + i - 13 for i in range(13, 25)},
    **{f"KP{i}": code for i, code in enumerate((82, 79, 80, 81, 75, 76, 77, 71, 72, 73))},
    "KPDOT": 83,
    "KPPLUS": 78,
    "KPMINUS": 74,
    "KPSLASH": 98,
}
ALIASES = {
    "CTRL": "LEFTCTRL",
    "CONTROL": "LEFTCTRL",
    "ALT": "LEFTALT",
    "SHIFT": "LEFTSHIFT",
    "SUPER": "LEFTMETA",
    "META": "LEFTMETA",
    "RETURN": "ENTER",
    "ESCAPE": "ESC",
}
BUTTONS = {
    "left": 272,
    "right": 273,
    "middle": 274,
    "side": 275,
    "extra": 276,
    "back": 278,
    "forward": 277,
}


def key_code(name):
    if not isinstance(name, str):
        raise ValueError("expected a Linux key name")
    normalized = name.upper().removeprefix("KEY_")
    normalized = ALIASES.get(normalized, normalized)
    if normalized not in KEYS:
        raise ValueError(f"unknown Linux key name {name!r}")
    return KEYS[normalized]


_PLAIN = "abcdefghijklmnopqrstuvwxyz0123456789`-=[]\\;',./ "
_SHIFTED = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%^&*()~_+{}|:"<>?'
_SHIFT_BASE = "abcdefghijklmnopqrstuvwxyz1234567890`-=[]\\;',./"


def text_codes(value):
    """Translate printable ASCII for a US keyboard layout."""
    result = []
    for index, char in enumerate(value):
        if char in _PLAIN:
            name = (
                "SPACE"
                if char == " "
                else (
                    char.upper()
                    if char.isalnum()
                    else {
                        "`": "GRAVE",
                        "-": "MINUS",
                        "=": "EQUAL",
                        "[": "LEFTBRACE",
                        "]": "RIGHTBRACE",
                        "\\": "BACKSLASH",
                        ";": "SEMICOLON",
                        "'": "APOSTROPHE",
                        ",": "COMMA",
                        ".": "DOT",
                        "/": "SLASH",
                    }[char]
                )
            )
            result.append((KEYS[name],))
        elif char in _SHIFTED:
            base = _SHIFT_BASE[_SHIFTED.index(char)]
            result.append((KEYS["LEFTSHIFT"], text_codes(base)[0][0]))
        else:
            raise ValueError(
                f"character {index + 1} {char!r} is unsupported; "
                "text needs printable ASCII on a US keyboard layout"
            )
    return result


class UInput:
    def __init__(self, path="/dev/uinput"):
        self.fd = -1
        self.held = {}
        try:
            self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            for kind in (EV_KEY, EV_REL):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, kind)
            for code in sorted(set(KEYS.values()) | set(BUTTONS.values())):
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            for code in (REL_HWHEEL, REL_WHEEL):
                fcntl.ioctl(self.fd, UI_SET_RELBIT, code)
            # BUS_VIRTUAL; no Logitech identity, so discovery cannot select this device.
            setup = struct.pack("@HHHH80sI", 6, 0, 0, 1, b"Maestro virtual input", 0)
            fcntl.ioctl(self.fd, UI_DEV_SETUP, setup)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError as exc:
            if self.fd >= 0:
                os.close(self.fd)
                self.fd = -1
            raise OSError(
                f"cannot create Maestro input via {path}: {exc}; "
                "see docs/configuration.md (uinput access)"
            ) from exc

    def _emit(self, kind, code, value):
        data = EVENT.pack(0, 0, kind, code, value) + EVENT.pack(0, 0, EV_SYN, 0, 0)
        if os.write(self.fd, data) != len(data):
            raise OSError("short write to uinput")

    def press(self, code):
        count = self.held.get(code, 0)
        if count == 0:
            self._emit(EV_KEY, code, 1)
        self.held[code] = count + 1

    def release(self, code):
        count = self.held.get(code, 0)
        if count <= 1:
            if count:
                self._emit(EV_KEY, code, 0)
            self.held.pop(code, None)
        else:
            self.held[code] = count - 1

    def chord(self, keys):
        codes = [key_code(k) for k in keys]
        pressed = []
        try:
            for code in codes:
                self.press(code)
                pressed.append(code)
        finally:
            for code in reversed(pressed):
                self.release(code)

    def scroll(self, steps, horizontal=False):
        self._emit(EV_REL, REL_HWHEEL if horizontal else REL_WHEEL, steps)

    def close(self):
        if self.fd < 0:
            return
        try:
            for code in list(self.held):
                self._emit(EV_KEY, code, 0)
        finally:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            finally:
                os.close(self.fd)
                self.fd = -1
                self.held.clear()
