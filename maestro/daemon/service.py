"""Serialized daemon loop: one owner of HID++, events, IPC, and actions."""

from __future__ import annotations

import atexit
import copy
import logging
import select
import signal
import time
from pathlib import Path

from maestro import hidpp, mouse

from .actions import Actions
from .catalog import catalog as action_catalog
from .catalog import control_device
from .config import (
    ConfigError,
    ConfigFile,
    full_config,
    validate_action,
    validate_expanded_action,
    validate_settings,
)
from .events import (
    WIRELESS_DEVICE_STATUS,
    Diversion,
    IdentityChanged,
    adopt_channels,
    decode,
    same_endpoint,
    supported_device,
)
from .gestures import Gesture, WheelAccumulator
from .ipc import Server
from .profiles import resolve, setting_rule
from .uinput import UInput
from .windows import Windows

LOG = logging.getLogger("maestrod")
DEVICE_ERRORS = (hidpp.HidppError, hidpp.NoResponse, OSError, ValueError)


def check_other_owners(proc=Path("/proc")):
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text().strip()
            args = (entry / "cmdline").read_bytes().split(b"\0")[:2]
            names = {comm} | {Path(a.decode(errors="replace")).name for a in args}
        except OSError:
            continue
        if names & {"solaar", "logid", "logiops"}:
            raise RuntimeError(f"stop Solaar/logiops before running maestrod (PID {entry.name})")


def apply_settings(device, settings, before_write=None):
    """Skip equal settings; preserve every option the config does not own."""
    if not supported_device(device) or not getattr(device, "writable", False):
        return ["mouse identity could not be verified; writes are disabled"]
    errors = []
    for key, value in settings.items():
        try:
            if key == "dpi":
                current = mouse.dpi(device)
                if current is None or current.current != value:
                    if before_write is not None:
                        before_write(key)
                    if mouse.set_dpi(device, value) != value:
                        raise ValueError("DPI readback differs from the requested value")
            elif key == "smartshift":
                current = mouse.smartshift(device)
                if current is None or any(getattr(current, k) != v for k, v in value.items()):
                    if before_write is not None:
                        before_write(key)
                    actual = mouse.set_smartshift(device, **value)
                    if actual is None or any(getattr(actual, k) != v for k, v in value.items()):
                        raise ValueError("SmartShift readback differs from the requested value")
            elif key == "invert":
                current = mouse.wheel(device)
                if current is None or current.inverted != value:
                    if before_write is not None:
                        before_write(key)
                    actual = mouse.set_wheel(device, inverted=value)
                    if actual is None or actual.inverted != value:
                        raise ValueError(
                            "scroll direction readback differs from the requested value"
                        )
        except DEVICE_ERRORS as exc:
            errors.append(f"{key}: {exc}")
    return errors


def snapshot_hardware(session, snapshots, required_key):
    """Read live values at the first write, including a just-recovered session."""
    for saved, settings in snapshots:
        if saved is session:
            if required_key not in settings:
                raise ValueError(f"cannot snapshot {required_key} before writing it")
            return
    if not session.validate_identity():
        raise hidpp.NoResponse(session.errors[0])
    settings = {}
    dpi = mouse.dpi(session.device)
    smartshift = mouse.smartshift(session.device)
    wheel = mouse.wheel(session.device)
    if dpi is not None:
        settings["dpi"] = dpi.current
    if smartshift is not None:
        settings["smartshift"] = {"mode": smartshift.mode, "threshold": smartshift.threshold}
    if wheel is not None:
        settings["invert"] = wheel.inverted
    if required_key not in settings:
        raise ValueError(f"cannot snapshot {required_key} before writing it")
    snapshots.append((session, settings))


def restore_hardware(snapshots):
    errors = []
    for session, settings in snapshots:
        if not session.validate_identity():
            errors.append(f"{session.diversion.name}: identity changed; hardware rollback skipped")
            continue
        errors.extend(
            f"{session.diversion.name}: {error}"
            for error in apply_settings(session.device, settings)
        )
    return errors


def confirm_settings(actual, requested, raw, identity, *, readback=False):
    for key, value in requested.items():
        fields = value.items() if isinstance(value, dict) else [(None, value)]
        for field, expected in fields:
            observed = actual.get(key)
            if field is not None:
                observed = observed.get(field) if isinstance(observed, dict) else None
            if observed != expected:
                label = f"{key}.{field}" if field else key
                rule = setting_rule(raw, identity, key, field)
                if readback:
                    raise ValueError(
                        f"{label} readback is {observed!r}, expected {expected!r}; "
                        f"effective setting from {rule}"
                    )
                raise ValueError(f"{label} request is overridden by {rule}: {observed!r}")


def device_identity(device):
    return (
        device.node.bus,
        device.node.vendor,
        device.node.product,
        device.wpid,
        device.kind,
        device.model,
    )


class MouseSession:
    def __init__(self, device, actions, endpoint_guard=None):
        self.device = device
        self.original_identity = device_identity(device)
        self.actions = actions
        self.diversion = Diversion(device, guard=endpoint_guard)
        self.identity = {
            "name": self.diversion.name,
            "path": device.node.path,
            "index": device.index,
        }
        self.indexes = {
            feature: device.feature_index(feature)
            for feature in (hidpp.REPROG_CONTROLS_V4, hidpp.THUMB_WHEEL, WIRELESS_DEVICE_STATUS)
        }
        self.options = None
        self.requested = None
        self.pending = None
        self.pressed = set()
        self.releases = {}
        self.gesture = Gesture()
        self.gesture_cid = None
        self.wheel = WheelAccumulator()
        self.bindings = {}
        self.online = False
        self.verified = False
        self.identity_state = "uncertain"
        self.errors = []
        self.setting_errors = []
        self.binding_errors = []
        self.before_write = None
        self.last_reconnect = -100

    def configure(self, options, force=False):
        self.requested = options
        if not self.device.writable:
            self.suspend("read_only", "mouse identity could not be verified; writes are disabled")
            self.options = options
            return
        if self.pressed and self.online and self.verified:
            if not self.validate_identity():
                return
            self.pending = (options, force)
            return
        try:
            self._configure(options, force or not self.online or not self.verified)
        except IdentityChanged as exc:
            self.suspend("changed", str(exc))
        except DEVICE_ERRORS as exc:
            self.suspend("uncertain", str(exc))

    def suspend(self, state="uncertain", reason="mouse identity needs re-verification"):
        # Revoke action permission before releasing input. Ownership of mouse
        # diversion is independent of this temporary session state.
        self.online = self.verified = False
        self.identity_state = state
        self.errors = [reason]
        if self.requested is not None:
            self.pending = (self.requested, True)
        self.cancel()

    def validate_identity(self):
        try:
            self.diversion.check_endpoint()
        except IdentityChanged as exc:
            self.suspend("changed", str(exc))
        except DEVICE_ERRORS as exc:
            self.suspend("uncertain", str(exc))
        else:
            return True
        return False

    def _configure(self, options, force=False):
        self.diversion.check_endpoint()
        self.pending = None
        self.setting_errors = apply_settings(
            self.device, options["settings"], before_write=self.before_write
        )
        self.errors = list(self.setting_errors)
        setting_error_count = len(self.errors)
        bindings = {}
        desired = {}
        gesture_cid = None
        gesture = options["gesture"]
        for name, action in options["buttons"].items():
            if action is None:
                continue
            cid = self.diversion.cid(name)
            if cid is None or not self.diversion.controls[cid].divertable:
                self.errors.append(f"{name}: this mouse has no divertable control")
                continue
            desired[cid], bindings[cid] = False, action
        # An explicit mapping, including null (native), takes precedence.
        if gesture["enabled"] and gesture["button"] not in options["buttons"]:
            cid = self.diversion.cid(gesture["button"])
            if cid is not None:
                control = self.diversion.controls[cid]
                if control.raw_xy and control.divertable:
                    desired[cid], gesture_cid = True, cid
                else:
                    self.errors.append("gesture: this button has no raw XY diversion")
        # Remove obsolete diversions before introducing new ones.
        for cid in list(self.diversion.owned):
            if cid not in desired or self.diversion.owned[cid] != desired[cid]:
                self.diversion.disable(cid)
        for cid, raw in desired.items():
            if force and cid in self.diversion.owned:
                self.diversion._set(cid, True, raw)
            else:
                self.diversion.enable(cid, raw)
        thumb_divert = options["thumb_wheel"]["mode"] != "horizontal"
        if thumb_divert and self.indexes.get(hidpp.THUMB_WHEEL) is None:
            self.errors.append(
                "thumb_wheel: this mouse has no 0x2150 diversion; "
                "native horizontal scroll remains active"
            )
            thumb_divert = False
        if thumb_divert or self.diversion.thumb_owned:
            self.diversion.thumb(thumb_divert)
        self.diversion.check_endpoint()
        self.options = options
        self.bindings = bindings
        self.gesture_cid = gesture_cid
        self.gesture = Gesture(gesture["threshold"])
        self.wheel = WheelAccumulator(options["thumb_wheel"]["step"])
        self.online = self.verified = True
        self.identity_state = "verified"
        self.binding_errors = self.errors[setting_error_count:]
        if self.setting_errors:
            LOG.error("%s settings: %s", self.diversion.name, "; ".join(self.setting_errors))

    def event(self, event):
        kind, data = event
        if kind == "disconnected":
            self.suspend(reason="mouse disconnected")
            return
        if kind == "reconnect":
            now = time.monotonic()
            if now - self.last_reconnect > 0.5:
                self.last_reconnect = now
                self.suspend(reason="mouse reconnected; reapplying configuration")
                if self.requested is not None:
                    self.configure(self.requested, force=True)
            return
        if self.options is None or not self.online or not self.verified:
            self.cancel()
            return
        if not self.validate_identity():
            return
        if kind == "buttons":
            current = data & set(self.diversion.owned)
            previous = self.pressed
            self.pressed = current
            for cid in previous - current:
                if cid == self.gesture_cid:
                    direction = self.gesture.end()
                    if direction:
                        self.actions.execute(
                            self.options["gesture"].get(direction),
                            owner=self,
                            trigger=f"gesture.{direction}",
                        )
                else:
                    release = self.releases.pop(cid, None)
                    if release:
                        release()
            for cid in current - previous:
                if cid == self.gesture_cid:
                    self.gesture.begin()
                else:
                    self.releases[cid] = self.actions.begin(
                        self.bindings[cid], owner=self, trigger=f"button.{cid}"
                    )
            if not current and self.pending is not None:
                self.configure(*self.pending)
        elif kind == "move":
            self.gesture.move(*data)
        elif kind == "thumb" and self.diversion.thumb_owned:
            count = self.wheel.feed(data[0], start=data[1])
            options = self.options["thumb_wheel"]
            for _ in range(abs(count)):
                self.actions.wheel(options["mode"], 1 if count > 0 else -1, options, owner=self)

    def cancel(self):
        self.actions.cancel_owner(self)
        self.gesture.end()
        for release in list(self.releases.values()):
            release()
        self.releases.clear()
        self.pressed.clear()

    def reconcile(self, options):
        if not self.device.writable:
            self.suspend("read_only", "mouse identity could not be verified; writes are disabled")
            return
        if not self.validate_identity() or self.pressed:
            return
        try:
            self.device.ping(timeout=0.2)
            if not self.online or not self.verified or self.pending is not None:
                self.configure(options, force=True)
                return
            reset = any(
                self.diversion.reporting(cid) & (0x11 if raw else 1) != (0x11 if raw else 1)
                for cid, raw in self.diversion.owned.items()
            )
            if self.diversion.thumb_owned:
                reset |= not bool(self.device.call(hidpp.THUMB_WHEEL, 1)[0] & 1)
            if reset:
                self.configure(options, force=True)
            else:
                self.setting_errors = apply_settings(self.device, options["settings"])
                self.errors = self.setting_errors + self.binding_errors
                if self.setting_errors:
                    LOG.error(
                        "%s settings: %s", self.diversion.name, "; ".join(self.setting_errors)
                    )
        except IdentityChanged as exc:
            self.suspend("changed", str(exc))
        except DEVICE_ERRORS as exc:
            self.suspend(reason=str(exc))

    def close(self):
        try:
            self.suspend("closing", "daemon is stopping")
        finally:
            # A failed pairing read is not permission to forget a diverted
            # control. Each retry still verifies the original endpoint.
            for _ in range(3):
                errors = self.diversion.close()
                if not self.diversion.owned and not self.diversion.thumb_owned:
                    break
        return errors


class Daemon:
    def __init__(
        self, config=None, output_factory=UInput, discover=None, windows=None, server_factory=Server
    ):
        self.config = config or ConfigFile()
        self.output_factory = output_factory
        self.discover = discover
        self.windows = windows or Windows()
        self.server_factory = server_factory
        self.output = self.actions = self.server = None
        self.sessions = []
        self.retired_sessions = []
        self.failed_channels = set()
        self.devices = []
        self.sleeping = []
        self.scan_errors = []
        self.reload_error = None
        self.stop = self.reload_requested = False
        self.closed = False
        self.window = {}

    def options(self, session):
        return resolve(self.config.raw, session.identity, self.window)

    def refresh_config(self):
        self.reload_error = None
        if not self.config.reload():
            self.reload_error = self.config.error
            LOG.error("%s", self.reload_error)
            return False
        self.actions.cancel_all()
        self.actions.automations = self.config.raw.get("automations", {})
        self.actions.dispatch = self.config.raw.get("hyprland_dispatch", "auto")
        errors = []
        for session in self.sessions:
            session.cancel()
            session.configure(self.options(session))
            errors.extend(f"{session.diversion.name}: {error}" for error in session.setting_errors)
            if not session.online or not session.verified:
                errors.append(
                    f"{session.diversion.name}: session suspended or unverified: "
                    + "; ".join(session.errors)
                )
        if errors:
            self.reload_error = "; ".join(errors)
            LOG.error("configuration reload: %s", self.reload_error)
            return False
        return True

    def discover_devices(self):
        try:
            scan = self.discover() if self.discover is not None else hidpp.scan_devices()
        except DEVICE_ERRORS as exc:
            self.scan_errors = [str(exc)]
            for session in self.sessions:
                session.suspend(reason=f"discovery is uncertain: {exc}")
            return
        # List injection remains useful for small lifecycle tests.
        if isinstance(scan, list):
            scan = hidpp.ScanResult(devices=scan)
        found = scan.devices
        self.sleeping, self.scan_errors = scan.sleeping, scan.errors
        old_devices = self.devices
        existing = {(s.device.node.path, s.device.index): s for s in self.sessions}
        sleeping = {(s.path, s.index): s for s in scan.sleeping}
        catalog = []
        new = []
        adopt_channels(found)
        try:
            for device in found:
                key = (device.node.path, device.index)
                previous = existing.pop(key, None)
                if previous is not None:
                    old = previous.device
                    if not device.writable:
                        previous.suspend(reason="discovery could not verify writable identity")
                        catalog.append(old)
                        continue
                    if previous.original_identity != device_identity(device):
                        self._retire(previous)
                        previous = None
                if previous is None:
                    previous = next(
                        (
                            s
                            for s in self.retired_sessions
                            if (s.device.node.path, s.device.index) == key
                            and s.original_identity == device_identity(device)
                        ),
                        None,
                    )
                    if previous is not None:
                        self.retired_sessions.remove(previous)
                        self.sessions.append(previous)
                if previous is not None:
                    # Preserve ownership when replacing a failed reader or
                    # read-only Device after a fresh scan verifies its identity.
                    needs_reader = id(previous.device.channel) in self.failed_channels
                    identity_changed = (
                        device_identity(previous.device) != previous.original_identity
                    )
                    became_writable = not previous.device.writable and device.writable
                    if device.writable and (needs_reader or identity_changed or became_writable):
                        previous.device = previous.diversion.device = device
                        previous.diversion.guard = self._guard(device)
                        previous.indexes = {
                            feature: device.feature_index(feature) for feature in previous.indexes
                        }
                    if not device.writable:
                        previous.suspend(reason="discovery could not verify writable identity")
                    elif became_writable or not previous.online or not previous.verified:
                        previous.configure(self.options(previous), force=True)
                    catalog.append(previous.device)
                    continue
                catalog.append(device)
                if supported_device(device):
                    new.append(device)
            for key, previous in existing.items():
                asleep = sleeping.get(key)
                if asleep is not None and asleep.wpid == previous.device.wpid:
                    previous.suspend(reason="mouse is asleep or out of range")
                    catalog.append(previous.device)
                else:
                    # Absence from an incomplete scan is not evidence of
                    # replacement. Only an authoritative endpoint check can
                    # retire the session; timeouts keep ownership suspended.
                    previous.suspend(reason="discovery is uncertain; retrying original identity")
                    previous.validate_identity()
                    if previous.identity_state == "changed":
                        self._retire(previous)
                    else:
                        catalog.append(previous.device)
            self.devices = catalog
            for device in new:
                session = MouseSession(device, self.actions, endpoint_guard=self._guard(device))
                # Record ownership before configure can perform the first write.
                self.sessions.append(session)
                session.configure(self.options(session))
                LOG.info(
                    "connected %s at %s slot %s",
                    session.identity["name"],
                    device.node.path,
                    device.index,
                )
        finally:
            used = {id(d.channel) for d in self.devices}
            used.update(id(s.device.channel) for s in self.sessions + self.retired_sessions)
            hidpp.close_devices([d for d in old_devices + found if id(d.channel) not in used])
            self.failed_channels.intersection_update(used)

    def _guard(self, device):
        return (lambda: same_endpoint(device)) if self.discover is None else None

    def _retire(self, session):
        session.suspend("changed", "the original endpoint was replaced or removed")
        self.sessions.remove(session)
        if session.diversion.owned or session.diversion.thumb_owned:
            # Keep both fd and ownership until the verified original returns,
            # or shutdown can retry safe cleanup. Never mutate Device.writable
            # because a probe of its receiver slot failed.
            self.retired_sessions.append(session)

    def handle(self, message):
        op = message.get("op")
        if op not in (
            "status",
            "set",
            "reload",
            "diagnose",
            "catalog",
            "controls",
            "config_get",
            "config_apply",
            "config_backups",
            "config_restore",
            "config_undo",
            "test_action",
        ):
            raise ValueError("unknown IPC operation")
        allowed = {"op"} if op != "set" else {"op", "device", "settings", "selector"}
        if op == "diagnose":
            allowed.add("devices")
        if op == "config_apply":
            allowed.add("config")
        if op == "config_restore":
            allowed.add("name")
        if op == "test_action":
            allowed.add("action")
        if set(message) - allowed:
            raise ValueError("unknown IPC field")
        if op == "reload":
            if not self.refresh_config():
                raise ConfigError(self.reload_error)
            return {"ok": True}
        if op == "catalog":
            return {"ok": True, "catalog": action_catalog()}
        if op == "config_get":
            return {"ok": True, "config": full_config(self.config.raw)}
        if op == "config_backups":
            return {"ok": True, "backups": self.config.backups()}
        if op in ("config_apply", "config_restore", "config_undo"):
            previous = copy.deepcopy(self.config.raw)
            previous_bytes = self.config.path.read_bytes() if self.config.path.exists() else b"{}\n"
            name = (
                self.config.apply(message.get("config"))
                if op == "config_apply"
                else self.config.restore(message.get("name"))
                if op == "config_restore"
                else self.config.undo(finalize=False)
            )
            snapshots = []
            try:
                for session in self.sessions:
                    session.before_write = lambda key, current=session: snapshot_hardware(
                        current, snapshots, key
                    )
                try:
                    if not self.refresh_config():
                        raise ConfigError(self.reload_error or "configuration reload failed")
                finally:
                    for session in self.sessions:
                        session.before_write = None
                if op == "config_undo":
                    self.config.finalize_undo(name, previous_bytes)
            except Exception as exc:
                rollback_errors = []
                try:
                    self.config.replace(previous, backup=False)
                    if not self.refresh_config():
                        rollback_errors.append(
                            f"previous config reload: {self.reload_error or 'unknown error'}"
                        )
                except Exception as rollback_exc:
                    rollback_errors.append(f"config rollback: {rollback_exc}")
                try:
                    rollback_errors.extend(restore_hardware(snapshots))
                except Exception as rollback_exc:
                    rollback_errors.append(f"hardware rollback: {rollback_exc}")
                if rollback_errors:
                    raise ConfigError(f"{exc}; rollback: {'; '.join(rollback_errors)}") from exc
                raise
            return {"ok": True, "backup": name, "reloaded": True}
        if op == "test_action":
            action = message.get("action")
            validate_action(action, "action", self.config.raw.get("automations", {}))
            validate_expanded_action(action, self.config.raw.get("automations", {}), "action")
            if self.actions is None:
                raise RuntimeError("daemon input is unavailable")
            if action and action["type"] in ("sequence", "automation"):
                if not self.actions.start_sequence(action, trigger="test-action"):
                    raise ValueError("test action is already running")
            else:
                self.actions.execute(action)
            return {"ok": True}
        if op == "controls":
            devices = self.handle({"op": "status"})["devices"]
            sessions = {id(s.device): s for s in self.sessions}
            physical = self.devices or [s.device for s in self.sessions]
            return {
                "ok": True,
                "daemon": True,
                "devices": [
                    control_device(
                        status,
                        i,
                        getattr(sessions.get(id(physical[i])), "diversion", None),
                        self.config.raw,
                    )
                    for i, status in enumerate(devices)
                    if status.get("supported")
                ],
            }
        if op == "status":
            devices = []
            sessions = {id(s.device): s for s in self.sessions}
            for device in self.devices or [s.device for s in self.sessions]:
                session = sessions.get(id(device))
                try:
                    if session:
                        session.diversion.check_endpoint(write=False)
                    info = mouse.status(device)
                except DEVICE_ERRORS as exc:
                    if session:
                        state = "changed" if isinstance(exc, IdentityChanged) else "uncertain"
                        session.suspend(state, str(exc))
                    info = {
                        "name": device.name(),
                        "path": device.node.path,
                        "index": device.index,
                        "model": device.model,
                        "supported": supported_device(device),
                        "error": str(exc),
                    }
                info["writable"] = device.writable
                if session:
                    info.update(
                        online=session.online,
                        profile=(session.options or {}).get("profile"),
                        errors=session.errors,
                        diverted_controls=sorted(session.diversion.owned),
                        thumb_diverted=session.diversion.thumb_owned,
                    )
                devices.append(info)
            return {
                "ok": True,
                "devices": devices,
                "config_error": self.config.error,
                "window": self.window,
                "window_error": self.windows.error,
                "sleeping": [vars(s) for s in self.sleeping],
                "scan_errors": self.scan_errors,
            }
        catalog = self.devices or [s.device for s in self.sessions]
        if op == "diagnose":
            indexes = message.get("devices", list(range(len(catalog))))
            if not isinstance(indexes, list) or any(
                type(i) is not int or not 0 <= i < len(catalog) for i in indexes
            ):
                raise ValueError("devices must be available zero-based device numbers")
            report = {
                "schema": 1,
                "devices": [mouse.diagnose(catalog[i]) for i in indexes],
                "sleeping": [
                    {
                        "connection": s.connection,
                        "wpid": f"{s.wpid:04X}" if s.wpid else None,
                        "slot": s.index if s.connection != "bluetooth" else None,
                    }
                    for s in self.sleeping
                ],
            }
            return {"ok": True, "report": report}
        settings = message.get("settings")
        validate_settings(settings)
        if not settings:
            raise ValueError("settings must not be empty")
        index = message.get("device", 0)
        if type(index) is not int or not 0 <= index < len(catalog):
            raise ValueError("device must be an available zero-based device number from status")
        device = catalog[index]
        session = next((s for s in self.sessions if s.device is device), None)
        if session is None:
            raise ValueError("unsupported Logitech device; writes are disabled for this mouse")
        selector = message.get("selector")
        if selector is not None and selector != {
            "path": device.node.path,
            "index": device.index,
            "model": device.model,
        }:
            raise ValueError("device identity changed; read status and retry")
        if not device.writable:
            session.suspend(
                "read_only", "mouse identity could not be verified; writes are disabled"
            )
            raise ValueError(session.errors[0])
        if not session.validate_identity():
            raise hidpp.NoResponse(session.errors[0])
        if not session.online or not session.verified:
            raise hidpp.NoResponse("mouse session is suspended; waiting for verified configuration")
        # Validate hardware support and persist only a change confirmed by readback.
        if session.pressed:
            raise ValueError("release diverted mouse buttons before changing settings")
        before = {}
        if "dpi" in settings:
            current = mouse.dpi(session.device)
            if current is None or settings["dpi"] not in current.choices:
                raise ValueError("DPI is unsupported; choose a value from status dpi.choices")
            before["dpi"] = current.current
        if "smartshift" in settings:
            current = mouse.smartshift(session.device)
            if current is None:
                raise ValueError("this mouse has no SmartShift")
            before["smartshift"] = {"mode": current.mode, "threshold": current.threshold}
        if "invert" in settings:
            current = mouse.wheel(session.device)
            if current is None:
                raise ValueError("this mouse has no configurable scroll direction")
            before["invert"] = current.inverted
        original_config = copy.deepcopy(self.config.raw)
        original_options = session.options
        persisted = False
        try:
            errors = apply_settings(session.device, settings)
            if errors:
                raise ValueError("; ".join(errors))
            self.config.save_device_settings(**session.identity, settings=settings)
            persisted = True
            options = self.options(session)
            confirm_settings(options["settings"], settings, self.config.raw, session.identity)
            session.configure(options)
            if not session.online or not session.verified or not session.validate_identity():
                raise hidpp.NoResponse("could not verify the effective mouse configuration")
            status = mouse.status(device)
            readback = {
                "dpi": (status.get("dpi") or {}).get("current"),
                "smartshift": status.get("smartshift") or {},
                "invert": (status.get("wheel") or {}).get("inverted"),
            }
            confirm_settings(readback, settings, self.config.raw, session.identity, readback=True)
        except Exception:
            if persisted and self.config.raw != original_config:
                try:
                    self.config.replace(original_config, backup=False)
                except (OSError, ConfigError):
                    LOG.exception("could not restore configuration after IPC failure")
            session.options = session.requested = original_options
            rollback_errors = (
                apply_settings(session.device, before)
                if session.validate_identity()
                else session.errors
            )
            if rollback_errors:
                LOG.error(
                    "could not restore settings after IPC failure: %s", "; ".join(rollback_errors)
                )
            raise
        return {"ok": True, "device": index, "settings": settings, "status": status}

    def process_events(self):
        channels = {id(s.device.channel): s.device.channel for s in self.sessions}
        for channel in channels.values():
            if id(channel) in self.failed_channels:
                continue
            try:
                packets = channel.read_events()
            except OSError as exc:
                LOG.warning("lost %s: %s", channel.path, exc)
                self.failed_channels.add(id(channel))
                lost = [s for s in self.sessions if s.device.channel is channel]
                for session in lost:
                    session.suspend(reason=f"event stream failed: {exc}")
                # Ownership and fd survive for cleanup; discovery can replace
                # the reader after verifying the original physical endpoint.
                continue
            for packet in packets:
                for session in self.sessions:
                    if session.device.channel is channel:
                        event = decode(packet, session.device, session.indexes)
                        if event is not None:
                            session.event(event)

    def run(self):
        if self.config.error:
            raise ConfigError(self.config.error)
        if getattr(self.windows, "desktop", "hyprland") != "hyprland" and not getattr(
            self.windows, "backend", None
        ):
            raise RuntimeError(
                "maestrod currently requires an Omarchy/Hyprland session; "
                "other desktops are not supported yet"
            )
        check_other_owners()
        old_handlers = {}
        atexit.register(self.close)
        try:

            def stop(signum, frame):
                self.stop = True

            def reload_config(signum, frame):
                self.reload_requested = True

            for signum, handler in (
                (signal.SIGTERM, stop),
                (signal.SIGINT, stop),
                (signal.SIGHUP, reload_config),
            ):
                old_handlers[signum] = signal.signal(signum, handler)
            # Lock before opening hidraw; fail before diversion if uinput is unavailable.
            self.server = self.server_factory(self.handle)
            self.output = self.output_factory()
            self.actions = Actions(
                self.output, dispatch=self.config.raw.get("hyprland_dispatch", "auto")
            )
            self.actions.automations = self.config.raw.get("automations", {})
            self.windows.connect()
            self.window = self.windows.poll()
            self.discover_devices()
            next_poll = next_reconcile = 0
            next_scan = time.monotonic() + 5
            while not self.stop:
                now = time.monotonic()
                self.process_events()
                self.server.poll(now)
                if self.reload_requested or self.config.changed():
                    self.reload_requested = False
                    self.refresh_config()
                if self.windows.dirty() or now >= next_poll:
                    window = self.windows.poll()
                    if window != self.window:
                        self.window = window
                        for session in self.sessions:
                            options = self.options(session)
                            if options != session.requested:
                                session.configure(options)
                    self.windows.connect()
                    next_poll = now + 0.75
                if now >= next_scan:
                    check_other_owners()
                    self.discover_devices()
                    next_scan = now + 5
                if now >= next_reconcile:
                    # Safety net when a receiver did not deliver a wake notification.
                    for session in self.sessions:
                        session.reconcile(self.options(session))
                    next_reconcile = now + 10
                self.actions.reap()
                fds = [
                    s.device.channel.fd
                    for s in self.sessions
                    if s.device.channel.fd >= 0 and id(s.device.channel) not in self.failed_channels
                ]
                fds.append(self.server.listener.fileno())
                if self.windows.socket is not None:
                    fds.append(self.windows.socket.fileno())
                select.select(fds, [], [], 0.02)
        finally:
            self.close()
            for signum, handler in old_handlers.items():
                signal.signal(signum, handler)
            atexit.unregister(self.close)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.actions is not None:
            self.actions.cancel_all()
        for session in self.sessions + self.retired_sessions:
            try:
                errors = session.close()
                if errors:
                    LOG.error("cleanup %s: %s", session.identity["name"], "; ".join(errors))
            except Exception:
                LOG.exception("cleanup failed for %s", session.identity["name"])
        resources = [
            lambda: hidpp.close_devices(
                self.devices + [s.device for s in self.sessions + self.retired_sessions]
            ),
            self.windows.close,
        ]
        if self.output is not None:
            resources.append(self.actions.close if self.actions is not None else self.output.close)
        if self.server is not None:
            resources.append(self.server.close)
        for close in resources:
            try:
                close()
            except Exception:
                LOG.exception("resource cleanup failed")
