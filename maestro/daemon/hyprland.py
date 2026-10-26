"""Build a small, fixed set of Omarchy Lua dispatchers from structured actions."""

import json
import re

WORKSPACE = re.compile(r"(?:[1-9][0-9]?|e[+-][1-9][0-9]?)\Z")
WINDOW = re.compile(r"(?:class:[A-Za-z0-9_.-]{1,80}|address:0x[0-9a-fA-F]{1,16})\Z")
DIRECTION = re.compile(r"[lrud]\Z")
NO_ARG = {"fullscreen", "togglefloating", "killactive", "cyclenext"}
WITH_ARG = {
    "workspace": WORKSPACE,
    "movetoworkspace": WORKSPACE,
    "focuswindow": WINDOW,
    "movefocus": DIRECTION,
}


def build_dispatch(action):
    """Validate again at execution, so callers cannot bypass config validation."""
    if not isinstance(action, dict) or action.get("type") != "hyprland":
        raise ValueError("expected a hyprland action")
    dispatcher = action.get("dispatcher")
    arg = action.get("arg")
    if not isinstance(dispatcher, str):
        raise ValueError("Hyprland dispatcher must be a string")
    if dispatcher in NO_ARG:
        if set(action) != {"type", "dispatcher"}:
            raise ValueError(f"{dispatcher} takes no arg")
        return {
            "fullscreen": 'hl.dsp.window.fullscreen({mode="fullscreen"})',
            "togglefloating": 'hl.dsp.window.float({action="toggle"})',
            "killactive": "hl.dsp.window.close()",
            "cyclenext": "hl.dsp.window.cycle_next()",
        }[dispatcher]
    if dispatcher not in WITH_ARG:
        raise ValueError("unknown Hyprland dispatcher")
    if set(action) != {"type", "dispatcher", "arg"}:
        raise ValueError(f"{dispatcher} requires exactly one arg")
    if not isinstance(arg, str) or not WITH_ARG[dispatcher].fullmatch(arg):
        raise ValueError(f"invalid arg for {dispatcher}")
    value = arg if arg.isdecimal() else json.dumps(arg, ensure_ascii=True)
    if dispatcher == "workspace":
        return f"hl.dsp.focus({{workspace={value}}})"
    if dispatcher == "movetoworkspace":
        return f"hl.dsp.window.move({{workspace={value}}})"
    if dispatcher == "focuswindow":
        return f"hl.dsp.focus({{window={value}}})"
    return f"hl.dsp.focus({{direction={value}}})"
