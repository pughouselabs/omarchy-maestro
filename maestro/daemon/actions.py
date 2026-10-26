"""Actions and desktop shortcuts. Commands are argv lists, never shell text."""

from __future__ import annotations

import copy
import logging
import os
import subprocess
import threading
import time

from .config import MAX_DELAY_MS, MAX_DEPTH, MAX_STEPS, MAX_TEXT
from .hyprland import build_dispatch
from .input_owner import InputOwner
from .uinput import BUTTONS, key_code, text_codes

LOG = logging.getLogger("maestrod")


def desktop_name(env=None):
    env = os.environ if env is None else env
    desktop = env.get("XDG_CURRENT_DESKTOP", "").lower()
    if env.get("HYPRLAND_INSTANCE_SIGNATURE") or "hyprland" in desktop:
        return "hyprland"
    return desktop.split(":")[-1] or "unsupported"


class Actions:
    def __init__(
        self,
        output,
        desktop=None,
        dispatch="auto",
        run=subprocess.run,
        popen=subprocess.Popen,
        desktop_handler=None,
    ):
        self.output = output
        self.desktop = desktop or desktop_name()
        self.dispatch = dispatch
        self.run = run
        self.popen = popen
        self.children = []
        self.automations = {}
        self._runs = {}
        self._runs_lock = threading.Lock()
        self._children_lock = threading.Lock()
        self.input = InputOwner(output)
        self.now = time.monotonic
        # Extension point for a future compositor backend; none is implied.
        self.desktop_handler = desktop_handler

    def begin(self, action, *, owner=None, trigger=None):
        """Return a release callback for held chords/buttons (including drags)."""
        if not action or action["type"] == "none":
            return lambda: None
        kind = action["type"]
        if kind in ("sequence", "automation"):
            self.start_sequence(action, owner=owner, trigger=trigger)
            return lambda: None
        if kind in ("key", "mouse"):
            codes = (
                [key_code(k) for k in action["keys"]]
                if kind == "key"
                else [BUTTONS[action["button"]]]
            )
            token = self.input.press(codes, id(owner))
            return lambda: self.input.release(token)
        if kind == "command":
            with self._children_lock:
                self.children = [child for child in self.children if child.poll() is None]
                if len(self.children) >= 16:
                    raise RuntimeError("16 action commands are still running; refusing another")
                self.children.append(
                    self.popen(
                        action["argv"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                        start_new_session=True,
                    )
                )
        elif kind == "desktop":
            self.desktop_action(action["action"])
        elif kind == "hyprland":
            if not self._dispatch(["hyprctl", "dispatch", build_dispatch(action)]):
                raise RuntimeError("Hyprland dispatch failed")
        return lambda: None

    def execute(self, action, *, owner=None, trigger=None):
        if action and action["type"] in ("key", "mouse"):
            codes = (
                [key_code(k) for k in action["keys"]]
                if action["type"] == "key"
                else [BUTTONS[action["button"]]]
            )
            if not self.input.chord(codes, id(owner)):
                raise RuntimeError("input release remains pending")
            return
        release = self.begin(action, owner=owner, trigger=trigger)
        release()

    def _steps(self, action, automations=None):
        if action["type"] == "sequence":
            return action["steps"]
        definitions = self.automations if automations is None else automations
        return definitions[action["id"]]["steps"]

    def start_sequence(self, action, *, owner=None, trigger=None):
        key = (id(owner), trigger if trigger is not None else id(action))
        with self._runs_lock:
            if key in self._runs:
                return False
            cancel = threading.Event()
            thread = threading.Thread(
                target=self._run_sequence,
                args=(key, action, cancel, copy.deepcopy(self.automations)),
                daemon=True,
            )
            self._runs[key] = (cancel, thread)
            thread.start()
        return True

    def _run_sequence(self, key, action, cancel, automations=None):
        deadline = self.now() + 30
        try:
            stack = [
                (iter(self._steps(action, automations)), 1 if action["type"] == "automation" else 0)
            ]
            count = text_length = delay = 0
            while stack and not cancel.is_set() and self.now() < deadline:
                step = next(stack[-1][0], None)
                if step is None:
                    stack.pop()
                    continue
                kind = step["type"]
                if kind == "automation":
                    if cancel.is_set():
                        break
                    depth = stack[-1][1] + 1
                    if depth > MAX_DEPTH:
                        LOG.warning("sequence stopped: automation nesting exceeds 3 levels")
                        break
                    stack.append((iter(self._steps(step, automations)), depth))
                    continue
                count += 1
                if count > MAX_STEPS:
                    LOG.warning("sequence stopped: expanded steps exceed 50")
                    break
                if kind == "delay":
                    ms = step["ms"]
                    if type(ms) is not int or not 0 <= ms <= 5000:
                        LOG.warning("sequence stopped: delay must be 0-5000 ms")
                        break
                    delay += ms
                    if delay > MAX_DELAY_MS:
                        LOG.warning("sequence stopped: delays exceed 30000 ms")
                        break
                    cancel.wait(min(ms / 1000, max(0, deadline - self.now())))
                elif kind == "text":
                    text_length += len(step["text"])
                    if text_length > MAX_TEXT:
                        LOG.warning("sequence stopped: text exceeds 500 characters")
                        break
                    for codes in text_codes(step["text"]):
                        if cancel.is_set() or self.now() >= deadline:
                            break
                        if not self.input.chord(codes, key[0], cancel):
                            raise RuntimeError("sequence key release remains pending")
                elif kind in ("key", "mouse"):
                    codes = (
                        [key_code(name) for name in step["keys"]]
                        if kind == "key"
                        else [BUTTONS[step["button"]]]
                    )
                    if not self.input.chord(codes, key[0], cancel):
                        raise RuntimeError("sequence key release remains pending")
                else:
                    self.execute(step)
        except Exception:
            # An action error stops only this run; the daemon and input stay usable.
            LOG.exception("sequence action failed")
        finally:
            with self._runs_lock:
                self._runs.pop(key, None)

    def cancel_owner(self, owner):
        owner_id = id(owner)
        with self._runs_lock:
            for key, (event, _) in self._runs.items():
                if key[0] == owner_id:
                    event.set()
        self.input.cancel(owner_id)

    def cancel_all(self):
        with self._runs_lock:
            for event, _ in self._runs.values():
                event.set()
        self.input.cancel()

    def close(self):
        self.cancel_all()
        self.input.close()

    def reap(self):
        with self._children_lock:
            self.children = [child for child in self.children if child.poll() is None]

    def _dispatch(self, argv):
        result = self.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=0.7,
            check=False,
        )
        return result.returncode == 0

    def desktop_action(self, action):
        if self.desktop_handler is not None:
            return self.desktop_handler(action)
        if self.desktop != "hyprland":
            raise RuntimeError(
                "desktop actions support Omarchy/Hyprland only; "
                "use key or command actions on other desktops"
            )
        if action in ("workspace_previous", "workspace_next"):
            forward = action == "workspace_next"
            workspace = "e+1" if forward else "e-1"
            # focus({workspace=...}) is the Lua form used by Omarchy's own
            # bindings; hl.dsp.workspace is a table on current Omarchy.
            lua, legacy = f'hl.dsp.focus({{workspace="{workspace}"}})', ["workspace", workspace]
        elif action == "app_switcher":
            lua, legacy = "hl.dsp.window.cycle_next()", ["cyclenext"]
        elif action == "fullscreen":
            lua, legacy = 'hl.dsp.window.fullscreen({mode="fullscreen"})', ["fullscreen", "0"]
        elif action in ("menu", "apps"):
            if not self._dispatch(
                ["omarchy-menu", "toggle", "root" if action == "menu" else "apps"]
            ):
                raise RuntimeError("Omarchy menu command failed")
            return
        else:
            raise ValueError(f"unknown desktop action {action}")
        if self.dispatch != "legacy":
            if self._dispatch(["hyprctl", "dispatch", lua]):
                return
            if self.dispatch == "lua":
                raise RuntimeError("Hyprland Lua dispatch failed")
        if not self._dispatch(["hyprctl", "dispatch", *legacy]):
            raise RuntimeError("Hyprland dispatch failed")

    def wheel(self, mode, direction, config, *, owner=None):
        if mode == "volume":
            self.input.chord([key_code("VOLUMEUP" if direction > 0 else "VOLUMEDOWN")], id(owner))
        elif mode == "zoom":
            self.input.scroll(direction, key_code("CTRL"))
        elif mode == "tabs":
            self.input.chord(
                [key_code("CTRL"), key_code("PAGEDOWN" if direction > 0 else "PAGEUP")],
                id(owner),
            )
        elif mode == "workspaces":
            self.desktop_action("workspace_next" if direction > 0 else "workspace_previous")
        elif mode == "custom":
            self.execute(
                config.get("right" if direction > 0 else "left"),
                owner=owner,
                trigger="wheel.right" if direction > 0 else "wheel.left",
            )
