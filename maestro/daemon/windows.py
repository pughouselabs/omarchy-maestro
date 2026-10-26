"""Focused-window polling with optional Hyprland socket2 wakeups."""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

from .actions import desktop_name


class Windows:
    def __init__(self, env=None, run=subprocess.run, backend=None):
        self.env = os.environ if env is None else env
        self.run = run
        self.desktop = desktop_name(self.env)
        self.last = {}
        self.error = None
        self.socket = None
        self.buffer = b""
        self.backend = backend  # callable returning class/title for future ports

    def _call(self, argv):
        result = self.run(argv, capture_output=True, text=True, timeout=0.5, check=False)
        if result.returncode:
            raise OSError(f"{argv[0]} could not read the active window")
        return result.stdout

    def connect(self):
        if self.socket is not None or self.desktop != "hyprland":
            return
        signature = self.env.get("HYPRLAND_INSTANCE_SIGNATURE")
        runtime = self.env.get("XDG_RUNTIME_DIR")
        if not signature or not runtime or "/" in signature:
            return
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(0.1)
            connection.connect(str(Path(runtime) / "hypr" / signature / ".socket2.sock"))
            connection.setblocking(False)
        except OSError:
            connection.close()
            return
        self.socket = connection

    def dirty(self):
        if self.socket is None:
            return False
        changed = False
        try:
            for _ in range(16):
                data = self.socket.recv(8192)
                if not data:
                    self.close()
                    break
                self.buffer += data
                if len(self.buffer) > 65536:
                    self.buffer = b""
                    changed = True
                    continue
                lines = self.buffer.split(b"\n")
                self.buffer = lines.pop()
                watched = {
                    b"activewindow",
                    b"activewindowv2",
                    b"windowtitle",
                    b"windowtitlev2",
                    b"closewindow",
                    b"openwindow",
                    b"workspace",
                    b"workspacev2",
                    b"focusedmon",
                }
                changed |= any(line.split(b">>", 1)[0] in watched for line in lines)
        except BlockingIOError:
            pass
        except OSError:
            self.close()
        return changed

    def poll(self):
        try:
            if self.backend is not None:
                result = self.backend()
            elif self.desktop == "hyprland":
                window = json.loads(self._call(["hyprctl", "activewindow", "-j"]))
                result = {
                    "class": window.get("class") or window.get("initialClass") or "",
                    "title": window.get("title") or "",
                }
            else:
                self.error = (
                    "Per-app profiles support Hyprland only. "
                    "GNOME/KDE/Sway/X11 backends are not supported yet."
                )
                self.last = {}
                return self.last
            self.last, self.error = result, None
        except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired) as exc:
            # Do not retain the previous app's mappings after a failed query.
            self.last = {}
            self.error = str(exc)
        return self.last

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        self.buffer = b""
