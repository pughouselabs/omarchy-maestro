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
from .catalog import control_device, device_selector, valid_selector
from .config import (
    ConfigError,
    ConfigFile,
    full_config,
    read_config_file,
    validate_action,
    validate_expanded_action,
    validate_settings,
)
from .events import (
    IDENTITY_PROBLEM,
    WIRELESS_DEVICE_STATUS,
    ControlBusy,
    Diversion,
    IdentityChanged,
    RecordFailed,
    Unidentified,
    adopt_channels,
    decode,
    same_endpoint,
    supported_device,
    write_batch,
)
from .gestures import Gesture, WheelAccumulator
from .ipc import Server
from .ownership import DiversionLedger, device_key, find_other_owner, selector_tag
from .profiles import resolve, setting_rule
from .uinput import UInput
from .windows import Windows

LOG = logging.getLogger("maestrod")
DEVICE_ERRORS = (hidpp.HidppError, hidpp.NoResponse, OSError, ValueError)


STARTUP_CONFLICTS = ("solaar", "logid", "logiops")
# Display names, and the verb that fits: Solaar is an app, logiops a service.
OWNER_NAMES = {
    "solaar": ("Solaar", "Close"),
    "logid": ("logiops", "Stop"),
    "logiops": ("logiops", "Stop"),
}
OWNER_RECHECK = 15  # seconds between checks while another app owns HID++


def check_other_owners(proc=Path("/proc")):
    """Display name of a running app that owns HID++ (Solaar, logiops), else None.

    Only the app name leaves this function; process IDs and arguments do not.
    """
    found = find_other_owner(proc, STARTUP_CONFLICTS)
    return None if found is None else OWNER_NAMES.get(found[1], (found[1], "Close"))[0]


def owner_problem(name):
    verb = next((v for n, v in OWNER_NAMES.values() if n == name), "Close")
    return f"{name} is running and controls the mouse. {verb} {name} to use Maestro."


def apply_settings(device, settings, before_write=None):
    """Skip equal settings; preserve every option the config does not own.

    Every write passes the device's unit gate. A mouse that is no longer the
    session's (or cannot be identified) raises before anything is written.
    """
    if not supported_device(device) or not getattr(device, "writable", False):
        return ["mouse identity could not be verified; writes are disabled"]
    with write_batch(device):
        return _apply_settings(device, settings, before_write)


def _apply_settings(device, settings, before_write):
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
        except (IdentityChanged, Unidentified):
            raise
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
        try:
            failed = apply_settings(session.device, settings)
        except DEVICE_ERRORS as exc:
            session.identity_failed(exc)
            failed = [f"hardware rollback skipped: {exc}"]
        errors.extend(f"{session.diversion.name}: {error}" for error in failed)
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


def offline_status(device, exc):
    """The full status shape for a mouse that did not answer, marked offline.

    Every key mouse.status() always sends is present, so readers never need
    to special-case a disconnected mouse.
    """
    node = device.node
    wpid = getattr(device, "wpid", None)
    try:
        name = device.name()
    except DEVICE_ERRORS:
        name = getattr(device, "reported_name", None) or device.model or "Logitech mouse"
    return {
        "name": name,
        "path": node.path,
        "index": device.index,
        "receiver": bool(getattr(node, "is_receiver", False)),
        "connection": getattr(node, "connection", None),
        "wpid": f"{wpid:04X}" if wpid is not None else None,
        "model": device.model,
        "supported": supported_device(device),
        "online": False,
        "error": str(exc),
        **{key: None for key in ("battery", "dpi", "smartshift", "wheel", "thumb_wheel", "host")},
    }


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
    def __init__(self, device, actions, endpoint_guard=None, ledger=None):
        self.device = device
        self.original_identity = device_identity(device)
        self.actions = actions
        self.diversion = Diversion(device, guard=endpoint_guard, ledger=ledger)
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
        self.busy = {}  # cid or "thumb" -> ControlBusy held by another app
        self.record_problem = None  # set while the ownership record cannot be saved
        self.before_write = None
        self.last_reconnect = -100

    def configure(self, options, force=False):
        self.requested = options
        if not self.device.writable:
            self.suspend("read_only", "mouse identity could not be verified; writes are disabled")
            self.options = options
            return
        if self.diversion.unit_key is None:
            # No unit ID when the mouse was opened: read-only for good.
            self.suspend("unidentified", IDENTITY_PROBLEM)
            self.options = options
            return
        if self.pressed and self.online and self.verified:
            if not self.validate_identity():
                return
            self.pending = (options, force)
            return
        try:
            with self.diversion.gate.batch():
                self._configure(options, force or not self.online or not self.verified)
        except (IdentityChanged, Unidentified) as exc:
            self.identity_failed(exc)
        except (*DEVICE_ERRORS, ControlBusy, RecordFailed) as exc:
            self.suspend("uncertain", str(exc))

    def identity_failed(self, exc):
        """Suspend after the unit gate refused a write (or could not identify the mouse)."""
        if isinstance(exc, IdentityChanged):
            self.suspend("changed", str(exc))
        elif isinstance(exc, Unidentified):
            self.suspend("unidentified", IDENTITY_PROBLEM)
        else:
            self.suspend("uncertain", str(exc))

    @property
    def problem(self):
        """One plain status line when a control is unavailable, else None."""
        if self.identity_state == "unidentified" or self.diversion.unit_key is None:
            return IDENTITY_PROBLEM
        if self.record_problem:
            return self.record_problem
        return next((exc.status for exc in self.busy.values()), None)

    def release_buttons(self, expected=None, *, required=False):
        """Explicit recovery requested by the user; then take the controls over.

        The live unit ID is read first; a mouse that is no longer the one this
        session opened (or whose ID cannot be read) gets no write at all.
        """
        if self.pressed:
            raise ValueError("release the mouse buttons first, then try again")
        try:
            released = self.diversion.release_leftovers(expected, required=required)
        except IdentityChanged as exc:
            self.suspend("changed", str(exc))
            raise ValueError("device identity changed; read status and retry") from exc
        except DEVICE_ERRORS as exc:
            self.identity_failed(exc)
            raise
        self.busy = {}
        if self.requested is not None:
            self.configure(self.requested, force=True)
        return released

    def abandon(self):
        """Forget this session's diversions without any HID++ write.

        Used when a different physical mouse now answers at this session's
        position. The ownership record is left as it is, so the original
        mouse is still reported (and released only on request) if it returns.
        """
        self.diversion.owned.clear()
        self.diversion.flags.clear()
        self.diversion.thumb_owned = False
        self.diversion.thumb_flags = None
        self.diversion.leftovers.clear()
        self.busy = {}

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
        # A reconnect can be a different mouse of the same model in the same
        # receiver slot. Confirm the live unit ID before the first write (the
        # unit gate would refuse the write anyway; this fails before any work).
        self.diversion.verify_unit()
        # Note what an earlier Maestro run left diverted on this same mouse (a
        # crash or power loss can keep it diverted). Nothing is released here;
        # only the user's explicit Release button does that.
        self.diversion.check_leftovers()
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
        busy = {}
        record_problem = None
        for cid, raw in desired.items():
            try:
                if force and cid in self.diversion.owned:
                    self.diversion.reassert(cid)
                else:
                    self.diversion.enable(cid, raw)
            except (ControlBusy, RecordFailed) as exc:
                # Another app owns it, or ownership could not be recorded.
                # Leave it untouched; everything else works.
                if isinstance(exc, ControlBusy):
                    busy[cid] = exc
                else:
                    record_problem = exc.status
                bindings.pop(cid, None)
                if gesture_cid == cid:
                    gesture_cid = None
                if exc.status not in self.errors:
                    self.errors.append(exc.status)
        thumb_divert = options["thumb_wheel"]["mode"] != "horizontal"
        if thumb_divert and self.indexes.get(hidpp.THUMB_WHEEL) is None:
            self.errors.append(
                "thumb_wheel: this mouse has no 0x2150 diversion; "
                "native horizontal scroll remains active"
            )
            thumb_divert = False
        if thumb_divert or self.diversion.thumb_owned:
            try:
                self.diversion.thumb(thumb_divert)
            except ControlBusy as exc:
                busy["thumb"] = exc
                self.errors.append(exc.status)
            except RecordFailed as exc:
                record_problem = exc.status
                if exc.status not in self.errors:
                    self.errors.append(exc.status)
        if busy and busy.keys() != self.busy.keys():
            LOG.warning("%s: %s", self.diversion.name, "; ".join(str(exc) for exc in busy.values()))
        if record_problem and not self.record_problem:
            LOG.error("%s: %s", self.diversion.name, record_problem)
        self.busy = busy
        self.record_problem = record_problem
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
        if self.diversion.unit_key is None:
            self.suspend("unidentified", IDENTITY_PROBLEM)
            return
        if not self.validate_identity() or self.pressed:
            return
        try:
            self.device.ping(timeout=0.2)
            if not self.online or not self.verified or self.pending is not None:
                self.configure(options, force=True)
                return
            self.diversion.retry_record()
            reset = self.record_problem is not None
            reset |= any(
                self.diversion.reporting(cid) & (0x11 if raw else 1) != (0x11 if raw else 1)
                for cid, raw in self.diversion.owned.items()
            )
            if self.diversion.thumb_owned:
                reset |= not bool(self.device.call(hidpp.THUMB_WHEEL, 1)[0] & 1)
            # Retry a control another app held once that app lets it go.
            for cid in self.busy:
                if cid == "thumb":
                    reset |= not self.device.call(hidpp.THUMB_WHEEL, 1)[0] & 1
                else:
                    reset |= not self.diversion.reporting(cid) & 0x15
            if reset:
                self.configure(options, force=True)
            else:
                self.setting_errors = apply_settings(self.device, options["settings"])
                self.errors = self.setting_errors + self.binding_errors
                if self.setting_errors:
                    LOG.error(
                        "%s settings: %s", self.diversion.name, "; ".join(self.setting_errors)
                    )
        except (IdentityChanged, Unidentified) as exc:
            self.identity_failed(exc)
        except (*DEVICE_ERRORS, ControlBusy, RecordFailed) as exc:
            self.suspend(reason=str(exc))

    def close(self):
        """Undo this session's diversions, only on the mouse that was diverted.

        The live unit ID must match first. A different or unreadable one skips
        cleanup with nothing written: the other mouse's buttons are not ours
        to change, and the record keeps this mouse's entry so it is reported
        (and released on request) when it returns.
        """
        try:
            self.suspend("closing", "daemon is stopping")
        finally:
            errors = []
            if self.diversion.owned or self.diversion.thumb_owned:
                with self.diversion.gate.batch():
                    try:
                        self.diversion.verify_unit()
                    except DEVICE_ERRORS as exc:
                        self.abandon()
                        errors = [f"cleanup skipped: {exc}"]
                    else:
                        # A failed pairing read is not permission to forget a
                        # diverted control. Each retry still checks the endpoint.
                        # Every write, including each retry, rereads the unit
                        # ID first; one refusal ends cleanup with nothing more
                        # written and this mouse's record kept.
                        for _ in range(3):
                            try:
                                errors = self.diversion.close()
                            except (IdentityChanged, Unidentified) as exc:
                                self.abandon()
                                errors = [f"cleanup stopped: {exc}"]
                                break
                            if not self.diversion.owned and not self.diversion.thumb_owned:
                                break
        return errors


class Daemon:
    def __init__(
        self,
        config=None,
        output_factory=UInput,
        discover=None,
        windows=None,
        server_factory=Server,
        ledger=None,
    ):
        self.config = config or ConfigFile()
        self.ledger = ledger if ledger is not None else DiversionLedger()
        self.output_factory = output_factory
        self.discover = discover
        self.windows = windows or Windows()
        self.server_factory = server_factory
        self.output = self.actions = self.server = None
        self.sessions = []
        self.retired_sessions = []
        self.failed_channels = set()
        self.devices = []
        self.unidentified = set()  # (path, index) of mice whose unit ID cannot be read
        self.sleeping = []
        self.scan_errors = []
        self.reload_error = None
        self.stop = self.reload_requested = False
        self.closed = False
        self.window = {}
        self.paused_by = None  # display name of another HID++ owner while paused

    @property
    def paused_problem(self):
        return owner_problem(self.paused_by) if self.paused_by else None

    def pause(self, owner):
        """Hand the mice to another HID++ owner: release them and stop all HID++.

        Diversions are undone exactly as at shutdown, then every hidraw handle
        is closed. Discovery resumes once the other app is gone.
        """
        first = self.paused_by is None
        self.paused_by = owner
        if not first:
            return
        LOG.warning(
            "%s Waiting; checking again every %s seconds.", owner_problem(owner), OWNER_RECHECK
        )
        self._release_mice()

    def resume(self):
        if self.paused_by is None:
            return
        LOG.info("%s is no longer running; resuming", self.paused_by)
        self.paused_by = None

    def check_owner(self):
        """Pause or resume on another HID++ owner. True while paused."""
        owner = check_other_owners()
        if owner:
            self.pause(owner)
            return True
        self.resume()
        return False

    def _release_mice(self):
        if self.actions is not None:
            try:
                self.actions.cancel_all()
            except Exception:
                LOG.exception("could not cancel running actions")
        for session in self.sessions + self.retired_sessions:
            try:
                errors = session.close()
                if errors:
                    LOG.error("cleanup %s: %s", session.identity["name"], "; ".join(errors))
            except Exception:
                LOG.exception("cleanup failed for %s", session.identity["name"])
        try:
            hidpp.close_devices(
                self.devices + [s.device for s in self.sessions + self.retired_sessions]
            )
        finally:
            self.sessions, self.retired_sessions, self.devices = [], [], []
            self.sleeping, self.scan_errors = [], []
            self.unidentified = set()
            self.failed_channels = set()

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
        unverified = set()  # held positions whose unit ID could not be read: no session
        adopt_channels(found)
        try:
            for device in found:
                key = (device.node.path, device.index)
                previous = existing.pop(key, None)
                unit, unit_read = None, False
                if previous is not None:
                    old = previous.device
                    if not device.writable:
                        previous.suspend(reason="discovery could not verify writable identity")
                        catalog.append(old)
                        continue
                    if previous.original_identity != device_identity(device):
                        self._retire(previous)
                        previous = None
                    else:
                        # Same model and receiver slot is not the same mouse:
                        # a replacement paired into the slot has another unit ID.
                        unit, unit_read = selector_tag(device_key(device)), True
                        if unit != previous.diversion.unit_key:
                            if unit is None:
                                unverified.add(key)
                            self._retire_replaced(previous, unit is None)
                            previous = None
                if previous is None:
                    for s in list(self.retired_sessions):
                        if (s.device.node.path, s.device.index) != key or (
                            s.original_identity != device_identity(device)
                        ):
                            continue
                        if not unit_read:
                            unit, unit_read = selector_tag(device_key(device)), True
                        if unit is None:
                            # Still unidentified: keep holding the slot, scan
                            # after scan, until the unit ID reads back.
                            unverified.add(key)
                        elif previous is None and unit == s.diversion.unit_key:
                            previous = s  # the same mouse is back
                        else:
                            # A different, verified mouse now sits in its slot:
                            # never undivert its buttons on the old one's behalf.
                            self.retired_sessions.remove(s)
                            s.abandon()
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
                # A slot held for a mouse whose unit ID cannot be read gets no
                # session until the ID reads back. Any other mouse without a
                # readable unit ID gets a read-only session (see UnitGate).
                if supported_device(device) and key not in unverified:
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
            self.unidentified = unverified
            for device in new:
                try:
                    session = MouseSession(
                        device,
                        self.actions,
                        endpoint_guard=self._guard(device),
                        ledger=self.ledger,
                    )
                except DEVICE_ERRORS as exc:
                    # One unreadable mouse must not stop the daemon; the next
                    # scan retries it.
                    LOG.warning("could not open %s: %s", device.node.path, exc)
                    continue
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

    def _retire_replaced(self, session, unverified):
        """Retire a session whose slot now reports another (or no) unit ID.

        Nothing is written to the mouse there. A different verified mouse
        drops the old session's diversions from memory (its record stays for
        when it returns). An unreadable ID keeps them retired, unused, until
        the same unit ID reads back again.
        """
        LOG.warning(
            "%s at %s slot %s: %s",
            session.identity["name"],
            session.identity["path"],
            session.identity["index"],
            "unit ID unreadable; holding until it can be verified"
            if unverified
            else "a different mouse of the same model replaced it",
        )
        if not unverified:
            session.abandon()
        self._retire(session)

    def _pause_fields(self):
        if not self.paused_by:
            return {}
        return {"paused_by": self.paused_by, "problem": self.paused_problem}

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
            "release_buttons",
        ):
            raise ValueError("unknown IPC operation")
        allowed = {"op"} if op != "set" else {"op", "device", "settings", "selector"}
        if op in ("controls", "release_buttons"):
            allowed.add("device")
        if op == "release_buttons":
            allowed.add("selector")
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
        if self.paused_by and op in ("set", "release_buttons"):
            raise RuntimeError(self.paused_problem)
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
            previous_bytes = (
                read_config_file(self.config.path) if self.config.path.exists() else b"{}\n"
            )
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
            # The device list leaves out resolved options so the response stays
            # bounded with several mice; the app reads one mouse's options with
            # "device", which is bounded by the configuration budget.
            selected = message.get("device")
            physical = self.devices or [s.device for s in self.sessions]
            if selected is not None and (
                type(selected) is not int or not 0 <= selected < len(physical)
            ):
                raise ValueError("device must be an available zero-based device number")
            devices = self.handle({"op": "status"})["devices"]
            sessions = {id(s.device): s for s in self.sessions}
            return {
                "ok": True,
                "daemon": True,
                **self._pause_fields(),
                "devices": [
                    control_device(
                        status,
                        i,
                        getattr(sessions.get(id(physical[i])), "diversion", None),
                        self.config.raw if selected is not None else None,
                        include_options=selected is not None,
                    )
                    for i, status in enumerate(devices)
                    if status.get("supported") and selected in (None, i)
                ],
            }
        if op == "release_buttons":
            selected = message.get("device")
            physical = self.devices or [s.device for s in self.sessions]
            if selected is not None and (
                type(selected) is not int or not 0 <= selected < len(physical)
            ):
                raise ValueError("device must be an available zero-based device number")
            # A device number alone can point at another mouse after
            # discovery changes, so a targeted release must name the mouse it
            # was chosen as, and is refused before any write if that changed.
            selector = message.get("selector")
            if selected is not None and not valid_selector(selector):
                raise ValueError("release_buttons with device needs its selector from controls")
            if selected is None and selector is not None:
                raise ValueError("selector needs a device number")
            sessions = {id(s.device): s for s in self.sessions}
            results = []
            for i, device in enumerate(physical):
                session = sessions.get(id(device))
                if selected not in (None, i) or session is None:
                    continue
                if selector is not None and selector != device_selector(
                    device.node.path, device.index, device.model, session.diversion.unit_key
                ):
                    raise ValueError("device identity changed; read status and retry")
                if not session.validate_identity():
                    raise hidpp.NoResponse(session.errors[0])
                results.append(
                    {
                        "device": i,
                        "model": session.device.model,
                        # The cached tag above can be stale after a same-model
                        # swap; this rereads the live unit ID before any write.
                        "released": session.release_buttons(
                            selector["unit"] if selector is not None else None,
                            required=selector is not None,
                        ),
                    }
                )
            if selected is not None and not results:
                raise ValueError("unsupported Logitech device; writes are disabled for this mouse")
            return {"ok": True, "devices": results}
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
                    info = offline_status(device, exc)
                info["writable"] = device.writable
                if session:
                    info.update(
                        online=session.online,
                        profile=(session.options or {}).get("profile"),
                        errors=session.errors,
                        diverted_controls=sorted(session.diversion.owned),
                        thumb_diverted=session.diversion.thumb_owned,
                    )
                    if session.problem:
                        info["problem"] = session.problem
                    info["release_available"] = bool(session.busy)
                    info["unit_key"] = session.diversion.unit_key
                elif (device.node.path, device.index) in self.unidentified:
                    info["problem"] = IDENTITY_PROBLEM
                devices.append(info)
            return {
                "ok": True,
                "devices": devices,
                "config_error": self.config.error,
                "window": self.window,
                "window_error": self.windows.error,
                "sleeping": [vars(s) for s in self.sleeping],
                "scan_errors": self.scan_errors,
                **self._pause_fields(),
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
        if session.diversion.unit_key is None:
            session.suspend("unidentified", IDENTITY_PROBLEM)
            raise ValueError(IDENTITY_PROBLEM)
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
            try:
                errors = apply_settings(session.device, settings)
            except (IdentityChanged, Unidentified) as exc:
                session.identity_failed(exc)
                raise
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
            try:
                rollback_errors = (
                    apply_settings(session.device, before)
                    if session.validate_identity()
                    else session.errors
                )
            except DEVICE_ERRORS as exc:
                # The unit gate refused: a different or unidentified mouse.
                session.identity_failed(exc)
                rollback_errors = [f"rollback skipped: {exc}"]
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
            except (OSError, hidpp.NoResponse) as exc:
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
            # Another HID++ owner pauses the daemon instead of stopping it, so
            # the service never restart-loops; no hidraw is opened until it is gone.
            if not self.check_owner():
                self.discover_devices()
            next_poll = next_reconcile = 0
            next_scan = time.monotonic() + (OWNER_RECHECK if self.paused_by else 5)
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
                    if self.check_owner():
                        next_scan = now + OWNER_RECHECK
                    else:
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
        resources = [self._release_mice, self.windows.close]
        if self.output is not None:
            resources.append(self.actions.close if self.actions is not None else self.output.close)
        if self.server is not None:
            resources.append(self.server.close)
        for close in resources:
            try:
                close()
            except Exception:
                LOG.exception("resource cleanup failed")
