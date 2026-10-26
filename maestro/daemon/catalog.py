"""Curated actions for the settings app, checked against this Omarchy install."""

from .config import full_config
from .events import BUTTON_CIDS
from .profiles import resolve


def catalog():
    def key(*keys):
        return {"type": "key", "keys": list(keys)}

    def command(*argv):
        return {"type": "command", "argv": list(argv)}

    def hypr(dispatcher, arg=None):
        action = {"type": "hyprland", "dispatcher": dispatcher}
        if arg is not None:
            action["arg"] = arg
        return action

    def mouse(button):
        return {"type": "mouse", "button": button}

    def group(ident, label, rows):
        return {
            "id": ident,
            "label": label,
            "actions": [
                {"id": f"{ident}.{name}", "label": title, "description": detail, "action": action}
                for name, title, detail, action in rows
            ],
        }

    omarchy = [
        (
            "menu",
            "Omarchy menu",
            "Open the main menu",
            command("omarchy", "menu", "toggle", "root"),
        ),
        ("apps", "Apps", "Open the app launcher", command("omarchy", "menu", "toggle", "apps")),
        (
            "terminal",
            "Terminal",
            "Open the default terminal",
            command("omarchy", "launch", "terminal"),
        ),
        ("browser", "Browser", "Open the default browser", command("omarchy", "launch", "browser")),
        ("files", "Files", "Open the file manager", command("omarchy", "launch", "nautilus")),
        (
            "screenshot-region",
            "Screenshot region",
            "Copy a selected region",
            command("omarchy", "capture", "screenshot", "region", "copy"),
        ),
        (
            "screenshot-window",
            "Screenshot window",
            "Copy a window image",
            command("omarchy", "capture", "screenshot", "windows", "copy"),
        ),
        (
            "screenshot-full",
            "Screenshot screen",
            "Copy the full screen",
            command("omarchy", "capture", "screenshot", "fullscreen", "copy"),
        ),
        (
            "screen-record",
            "Start screen recording",
            "Record the screen",
            command("omarchy", "capture", "screenrecording"),
        ),
        (
            "screen-record-stop",
            "Stop screen recording",
            "Finish recording",
            command("omarchy", "capture", "screenrecording", "--stop-recording"),
        ),
        ("color-picker", "Color picker", "Pick a screen color", command("hyprpicker", "-a")),
        (
            "lock",
            "Lock screen",
            "Lock and turn off the display",
            command("omarchy", "system", "lock"),
        ),
        (
            "theme",
            "Choose theme",
            "Open the theme switcher",
            command("omarchy", "theme", "switcher"),
        ),
        (
            "background-next",
            "Next background",
            "Cycle the current theme background",
            command("omarchy", "theme", "bg", "next"),
        ),
        (
            "notifications",
            "Notification history",
            "Open notification history",
            command("omarchy", "shell", "notifications", "showHistory"),
        ),
        ("emoji", "Emoji picker", "Open the emoji picker", command("omarchy", "menu", "emoji")),
        (
            "clipboard",
            "Clipboard",
            "Open clipboard history",
            command("omarchy", "menu", "clipboard"),
        ),
        (
            "power",
            "Power menu",
            "Open power options",
            command("omarchy", "menu", "toggle", "system"),
        ),
        (
            "night-light",
            "Night light",
            "Toggle night light",
            command("omarchy", "toggle", "nightlight"),
        ),
        (
            "quiet",
            "Quiet notifications",
            "Toggle notification silencing",
            command("omarchy", "toggle", "notification", "silencing"),
        ),
    ]
    windows = [
        ("workspace-next", "Next workspace", "Focus the next workspace", hypr("workspace", "e+1")),
        (
            "workspace-previous",
            "Previous workspace",
            "Focus the previous workspace",
            hypr("workspace", "e-1"),
        ),
        (
            "move-one",
            "Move to workspace 1",
            "Move the window to workspace 1",
            hypr("movetoworkspace", "1"),
        ),
        (
            "move-two",
            "Move to workspace 2",
            "Move the window to workspace 2",
            hypr("movetoworkspace", "2"),
        ),
        ("focus-left", "Focus left", "Focus the window to the left", hypr("movefocus", "l")),
        ("focus-right", "Focus right", "Focus the window to the right", hypr("movefocus", "r")),
        ("focus-up", "Focus up", "Focus the window above", hypr("movefocus", "u")),
        ("focus-down", "Focus down", "Focus the window below", hypr("movefocus", "d")),
        (
            "focus-firefox",
            "Focus Firefox",
            "Focus a Firefox window",
            hypr("focuswindow", "class:firefox"),
        ),
        ("fullscreen", "Fullscreen", "Toggle fullscreen", hypr("fullscreen")),
        ("floating", "Floating window", "Toggle floating for the window", hypr("togglefloating")),
        ("close", "Close window", "Close the focused window", hypr("killactive")),
        ("next-window", "Next window", "Cycle to the next window", hypr("cyclenext")),
    ]
    media = [
        ("play-pause", "Play or pause", "Toggle media playback", key("PLAYPAUSE")),
        ("next", "Next track", "Skip to the next track", key("NEXTSONG")),
        ("previous", "Previous track", "Return to the previous track", key("PREVIOUSSONG")),
        ("volume-up", "Volume up", "Raise system volume", key("VOLUMEUP")),
        ("volume-down", "Volume down", "Lower system volume", key("VOLUMEDOWN")),
        ("mute", "Mute sound", "Toggle output mute", key("MUTE")),
        ("mic-mute", "Mute microphone", "Toggle microphone mute", key("MICMUTE")),
    ]
    browser = [
        ("back", "Back", "Go to the previous page", key("ALT", "LEFT")),
        ("forward", "Forward", "Go to the next page", key("ALT", "RIGHT")),
        ("new-tab", "New tab", "Open a new tab", key("CTRL", "T")),
        ("close-tab", "Close tab", "Close the current tab", key("CTRL", "W")),
        ("reopen-tab", "Reopen tab", "Restore the closed tab", key("CTRL", "SHIFT", "T")),
        ("next-tab", "Next tab", "Switch to the next tab", key("CTRL", "PAGEDOWN")),
        ("previous-tab", "Previous tab", "Switch to the previous tab", key("CTRL", "PAGEUP")),
        ("refresh", "Refresh page", "Reload the current page", key("CTRL", "R")),
        ("address", "Address bar", "Focus the address bar", key("CTRL", "L")),
    ]
    editing = [
        ("copy", "Copy", "Copy the selection", key("CTRL", "C")),
        ("cut", "Cut", "Cut the selection", key("CTRL", "X")),
        ("paste", "Paste", "Paste clipboard contents", key("CTRL", "V")),
        ("undo", "Undo", "Undo the last edit", key("CTRL", "Z")),
        ("redo", "Redo", "Redo the last edit", key("CTRL", "SHIFT", "Z")),
        ("select-all", "Select all", "Select all content", key("CTRL", "A")),
        ("save", "Save", "Save the current file", key("CTRL", "S")),
        ("find", "Find", "Find text", key("CTRL", "F")),
    ]
    zoom = [
        ("in", "Zoom in", "Increase zoom", key("CTRL", "EQUAL")),
        ("out", "Zoom out", "Decrease zoom", key("CTRL", "MINUS")),
        ("reset", "Reset zoom", "Return to default zoom", key("CTRL", "0")),
    ]
    mouse_actions = [
        ("left", "Left click", "Send a left click", mouse("left")),
        ("middle", "Middle click", "Send a middle click", mouse("middle")),
        ("right", "Right click", "Send a right click", mouse("right")),
        ("back", "Back click", "Send a back click", mouse("back")),
        ("forward", "Forward click", "Send a forward click", mouse("forward")),
        (
            "double",
            "Double click",
            "Send two left clicks",
            {
                "type": "sequence",
                "steps": [mouse("left"), {"type": "delay", "ms": 80}, mouse("left")],
            },
        ),
    ]

    def gesture(ident, label, tap, up, down, left, right):
        return {
            "id": ident,
            "label": label,
            "gesture": {"tap": tap, "up": up, "down": down, "left": left, "right": right},
        }

    def template(ident, name, description, steps):
        return {"id": ident, "name": name, "description": description, "steps": steps}

    return {
        "version": 1,
        "defaults": full_config({}),
        "groups": [
            group("omarchy", "Omarchy", omarchy),
            group("windows", "Windows and workspaces", windows),
            group("media", "Media", media),
            group("browser", "Browser", browser),
            group("editing", "Editing", editing),
            group("zoom", "Zoom", zoom),
            group("mouse", "Mouse", mouse_actions),
        ],
        "gesture_presets": [
            gesture(
                "windows",
                "Window navigation",
                {"type": "desktop", "action": "app_switcher"},
                {"type": "desktop", "action": "fullscreen"},
                {"type": "desktop", "action": "menu"},
                {"type": "desktop", "action": "workspace_previous"},
                {"type": "desktop", "action": "workspace_next"},
            ),
            gesture(
                "workspaces",
                "Workspaces",
                hypr("cyclenext"),
                hypr("workspace", "e-1"),
                hypr("workspace", "e+1"),
                hypr("workspace", "e-1"),
                hypr("workspace", "e+1"),
            ),
            gesture(
                "media",
                "Media",
                key("PLAYPAUSE"),
                key("VOLUMEUP"),
                key("VOLUMEDOWN"),
                key("PREVIOUSSONG"),
                key("NEXTSONG"),
            ),
            gesture(
                "zoom",
                "Zoom",
                key("CTRL", "0"),
                key("CTRL", "EQUAL"),
                key("CTRL", "MINUS"),
                key("CTRL", "MINUS"),
                key("CTRL", "EQUAL"),
            ),
        ],
        "smart_action_templates": [
            template(
                "paste-send",
                "Paste and send",
                "Paste the clipboard, then submit",
                [key("CTRL", "V"), {"type": "delay", "ms": 150}, key("ENTER")],
            ),
            template(
                "screenshot-region",
                "Screenshot region",
                "Select and copy a screen region",
                [command("omarchy", "capture", "screenshot", "region", "copy")],
            ),
            template(
                "morning-apps",
                "Morning apps",
                "Open the browser and terminal",
                [command("omarchy", "launch", "browser"), command("omarchy", "launch", "terminal")],
            ),
            template(
                "mute-and-lock",
                "Mute and lock",
                "Mute the output and lock the desktop",
                [
                    command("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"),
                    command("omarchy", "system", "lock"),
                ],
            ),
        ],
    }


BUTTON_LABELS = {
    "gesture": "Gesture button",
    "back": "Back button",
    "forward": "Forward button",
    "middle": "Middle button",
    "mode_shift": "Mode shift button",
}


def device_selector(path, index, model, unit):
    """The identity an explicit release must match: position alone can change."""
    return {"path": path, "index": index, "model": model, "unit": unit}


def valid_selector(value):
    return (
        isinstance(value, dict)
        and set(value) == {"path", "index", "model", "unit"}
        and isinstance(value["path"], str)
        and type(value["index"]) is int
        and isinstance(value["model"], str)
        and (value["unit"] is None or isinstance(value["unit"], str))
    )


def control_device(status, device_number, diversion=None, config=None, include_options=True):
    """The settings-app view of one mouse.

    Resolved options can be as large as the whole configuration, so a list of
    several mice leaves them out (include_options=False) and the app reads them
    for one mouse at a time.
    """
    # mouse.status() reads mouse.battery() on both the direct CLI and daemon paths.
    # Keep read errors and HID++ source details out of the settings-app contract.
    battery = status.get("battery")
    battery = (
        {key: battery[key] for key in ("percent", "charging", "status")}
        if isinstance(battery, dict)
        and all(key in battery for key in ("percent", "charging", "status"))
        else None
    )
    controls = getattr(diversion, "controls", {})
    buttons = []
    for name, label in BUTTON_LABELS.items():
        control = next((controls[cid] for cid in BUTTON_CIDS[name] if cid in controls), None)
        buttons.append(
            {"name": name, "label": label, "available": bool(control and control.divertable)}
        )
    gesture = next((controls[cid] for cid in BUTTON_CIDS["gesture"] if cid in controls), None)
    identity = {
        "name": status.get("model") or status.get("name"),
        "index": status.get("index"),
    }
    result = {
        "device": device_number,
        "model": status.get("model") or status.get("name"),
        "writable": bool(status.get("writable", False)),
        "identity": identity,
        "battery": battery,
        "buttons": buttons,
        "gesture": bool(gesture and gesture.raw_xy and gesture.divertable),
        "thumb_wheel": {"available": status.get("thumb_wheel") is not None},
        "dpi": status.get("dpi"),
        "smartshift": status.get("smartshift"),
        "scroll": {"inverted": (status.get("wheel") or {}).get("inverted", False)},
        "problem": status.get("problem"),
        "release_available": bool(status.get("release_available", False)),
        "selector": device_selector(
            status.get("path"),
            status.get("index"),
            status.get("model") or status.get("name"),
            getattr(diversion, "unit_key", None),
        ),
    }
    if include_options:
        result["options"] = resolve(config or {}, dict(identity, path=status.get("path")))
    return result
