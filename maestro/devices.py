"""Conservative identity checks for the supported Logitech MX mouse family.

Names are a fallback because the same model can have different wireless product
IDs over Unifying, Bolt, and Bluetooth. A product ID is used only when verified.
"""

from __future__ import annotations

import re

# Wireless product IDs from the locally installed Solaar device table. The 2S
# entry was also verified on the real receiver. Other models retain name fallback.
KNOWN_PRODUCTS = {
    0x4041: "MX Master",
    0x404A: "MX Anywhere 2",
    0x4069: "MX Master 2S",
    0x407B: "MX Vertical",
    0x4082: "MX Master 3",
}

# Bluetooth product IDs from Solaar's device descriptors. B360 is a keyboard
# reported in a local regression case; the other keyboard IDs are in the table.
KNOWN_BT_MICE = {
    0xB012: "MX Master",
    0xB019: "MX Master 2S",
    0xB020: "MX Vertical",
    0xB023: "MX Master 3",
}
KNOWN_BT_KEYBOARDS = {0xB350, 0xB35B, 0xB360}

_MODELS = (
    (re.compile(r"\bmx\s+master\s+4\b", re.I), "MX Master 4"),
    (re.compile(r"\bmx\s+master\s+3s\b", re.I), "MX Master 3S"),
    (re.compile(r"\bmx\s+master\s+3\b", re.I), "MX Master 3"),
    (re.compile(r"\bmx\s+master\s+2s\b", re.I), "MX Master 2S"),
    (re.compile(r"\bmx\s+master\b", re.I), "MX Master"),
    (re.compile(r"\bmx\s+anywhere\s+3s\b", re.I), "MX Anywhere 3S"),
    (re.compile(r"\bmx\s+anywhere\s+3\b", re.I), "MX Anywhere 3"),
    (re.compile(r"\bmx\s+anywhere\s+2s\b", re.I), "MX Anywhere 2S"),
    (re.compile(r"\bmx\s+anywhere\s+2\b", re.I), "MX Anywhere 2"),
    (re.compile(r"\bmx\s+vertical\b", re.I), "MX Vertical"),
    (re.compile(r"\bmx\s+ergo\s+s\b", re.I), "MX Ergo S"),
    (re.compile(r"\bmx\s+ergo\b", re.I), "MX Ergo"),
)


def model_for(name: str, product_id: int | None = None) -> str | None:
    """Return a supported model only after the caller has established mouse kind."""
    if product_id in KNOWN_PRODUCTS:
        return KNOWN_PRODUCTS[product_id]
    for pattern, model in _MODELS:
        if pattern.search(name):
            return model
    return None


_STRICT_BT_NAME = re.compile(
    r"^(?:Logitech\s+)?(?:Wireless\s+)?(?:Mouse\s+|Trackball\s+)?"
    r"(?P<model>MX\s+(?:Master(?:\s+(?:2S|3S|3|4))?|"
    r"Anywhere\s+(?:2S|2|3S|3)|Vertical|Ergo(?:\s+S)?))"
    r"(?:\s+(?:Wireless\s+)?(?:Mouse|Trackball))?(?:\s+for\s+Mac)?$",
    re.I,
)


def bluetooth_model(name: str, product_id: int) -> str | None:
    """Decide direct-Bluetooth eligibility from sysfs identity before I/O.

    Known keyboard products always lose, even if a misleading name contains an
    MX mouse model. Unknown products need an exact MX-family name, never a loose
    substring such as 'Mouse' or 'MX Master Keyboard'.
    """
    if product_id in KNOWN_BT_KEYBOARDS:
        return None
    if product_id in KNOWN_BT_MICE:
        return KNOWN_BT_MICE[product_id]
    match = _STRICT_BT_NAME.fullmatch(name.strip())
    return model_for(match.group("model")) if match else None


def plausible_mouse_name(name: str) -> bool:
    """Compatibility helper for strict MX-family Bluetooth name matching."""
    return bluetooth_model(name, 0) is not None
