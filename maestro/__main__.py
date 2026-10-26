"""maestro: Logitech MX mouse settings and shareable diagnostics.

  maestro status [--all] [--json]
  maestro diagnose [--json]
  maestro dpi <value> [--json]
  maestro smartshift [--mode ratchet|freespin] [--threshold 1-255] [--json]
  maestro scroll --invert on|off [--json]
  maestro release-buttons [--mouse N] [--json]

Selectors: --mouse N (0-based, as shown by status) or --device NAME-OR-PATH.
They may appear before or after the command. A receiver path shared by several
mice is ambiguous; use --mouse N or PATH:SLOT in that case.

Exit codes: 0 success (including an empty status); 1 device/protocol error;
2 no selected supported mouse, ambiguous selector, or invalid arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace

from . import hidpp, mouse
from .daemon import ipc
from .daemon.catalog import catalog as action_catalog
from .daemon.catalog import control_device, device_selector, valid_selector
from .daemon.config import (
    ConfigError,
    ConfigFile,
    _decode,
    full_config,
    read_config,
    validate_action,
)
from .daemon.events import (
    IDENTITY_PROBLEM,
    Diversion,
    IdentityChanged,
    Unidentified,
    guard_device,
    supported_device,
)
from .daemon.ownership import DiversionLedger


def _print_status(statuses: list[dict], numbers: list[int]) -> None:
    for n, s in zip(numbers, statuses, strict=False):
        # A mouse that stopped answering can come back with fewer keys.
        receiver = s.get("receiver")
        link = f"receiver slot {s.get('index')}" if receiver else "Bluetooth"
        where = [s.get("path") or "unknown path"] + ([link] if receiver is not None else [])
        offline = "error" in s
        print(
            f"[{n}] {s.get('name') or s.get('model') or 'Logitech mouse'}  ({', '.join(where)})"
            f"{'  disconnected' if offline else ''}"
            f"{'  unsupported' if not s.get('supported', True) else ''}"
        )
        if not s.get("supported", True):
            continue
        if s.get("problem"):
            print(f"    Problem     {s['problem']}")
        b = s.get("battery")
        if b and "percent" in b:
            print(f"    Battery     {b['percent']}% ({b['status']})")
        d = s.get("dpi")
        if d and "current" in d:
            step = f", steps of {d['step']}" if d.get("step") else ""
            print(f"    DPI         {d['current']} (range {d['minimum']}-{d['maximum']}{step})")
        ss = s.get("smartshift")
        if ss and "mode" in ss:
            print(f"    Wheel mode  {ss['mode']}, SmartShift threshold {ss['threshold']}")
        w = s.get("wheel")
        if w and "hires" in w:
            print(
                f"    Scrolling   {'smooth (hi-res)' if w['hires'] else 'standard'}"
                f"{', inverted' if w['inverted'] else ''}"
            )
        tw = s.get("thumb_wheel")
        if tw and "inverted" in tw:
            print(
                f"    Thumb wheel {'inverted' if tw['inverted'] else 'normal'}"
                f", resolution {tw['resolution'] if tw['resolution'] is not None else 'unknown'}"
            )
        h = s.get("host")
        if h and "current" in h:
            print(f"    Easy-Switch channel {h['current']} of {h['count']}")


def _add_selector(parser: argparse.ArgumentParser, *, suppress: bool = False) -> None:
    default = argparse.SUPPRESS if suppress else None
    parser.add_argument("--mouse", type=int, default=default, help="0-based mouse number")
    parser.add_argument("--device", default=default, help="mouse name, hidraw path, or path:slot")


def _supported_device(dev) -> bool:
    model = getattr(dev, "model", None)
    kind = getattr(dev, "kind", None)
    return model is not None and (
        kind == "mouse" or (kind == "trackball" and model in ("MX Ergo", "MX Ergo S"))
    )


def _select(mice: list, args: argparse.Namespace, *, all_by_default: bool) -> list:
    if args.mouse is not None and args.device is not None:
        raise ValueError("use either --mouse or --device")
    if args.mouse is not None:
        if not 0 <= args.mouse < len(mice):
            raise ValueError(f"no mouse {args.mouse}; found {len(mice)}")
        return [mice[args.mouse]]
    if args.device is not None:
        query = args.device.casefold()
        matches = [
            d
            for d in mice
            if query in d.name().casefold()
            or query == d.node.path.casefold()
            or query == f"{d.node.path}:{d.index}".casefold()
        ]
        if not matches:
            raise ValueError(f"no mouse matches {args.device!r}")
        if len(matches) > 1:
            raise ValueError(
                f"{args.device!r} matches {len(matches)} mice; use --mouse N or path:slot"
            )
        return matches
    if all_by_default:
        return mice
    return next(([m] for m in mice if _supported_device(m)), [])


def _absence() -> str:
    if mouse.last_scan.sleeping:
        return "Paired MX mouse is asleep or out of range; wake it and retry."
    if mouse.last_scan.errors:
        return "No reachable MX mouse; " + "; ".join(mouse.last_scan.errors)
    return "No supported MX mouse found (check pairing and Bluetooth connection)."


_DAEMON_FIELDS = {
    "writable",
    "online",
    "profile",
    "errors",
    "diverted_controls",
    "thumb_diverted",
    "release_available",
    "unit_key",
}


class _RemoteDevice:
    """Selection view over a status snapshot. Never opens a hardware channel."""

    def __init__(self, status):
        self.status = {key: value for key, value in status.items() if key not in _DAEMON_FIELDS}
        self.model = status.get("model") if status.get("supported") else None
        self.kind = "trackball" if self.model in ("MX Ergo", "MX Ergo S") else "mouse"
        self.writable = status.get("writable", False)
        self.node = SimpleNamespace(path=status["path"])
        self.index = status["index"]

    def name(self):
        return self.status["name"]


def _ipc_result(message):
    response = ipc.request(message)
    if not isinstance(response, dict) or response.get("ok") is not True:
        error = (
            response.get("error", "invalid daemon response")
            if isinstance(response, dict)
            else "invalid daemon response"
        )
        if isinstance(response, dict) and response.get("exit_code") == 2:
            raise ValueError(error)
        raise RuntimeError(error)
    return response


def _from_daemon(args, response):
    if not isinstance(response, dict) or response.get("ok") is not True:
        error = (
            response.get("error", "invalid daemon response")
            if isinstance(response, dict)
            else "invalid daemon response"
        )
        raise RuntimeError(error)
    problem = response.get("problem") if response.get("paused_by") else None
    if problem and args.command not in ("status", "diagnose"):
        # The service has handed the mouse to another app and sends no HID++.
        print(f"maestro: {problem}", file=sys.stderr)
        return 1
    mice = [_RemoteDevice(status) for status in response["devices"]]
    selected = _select(mice, args, all_by_default=args.command in ("status", "diagnose"))
    if args.command == "status":
        if args.mouse is None and args.device is None and not args.all:
            selected = [m for m in selected if _supported_device(m)]
        statuses = [m.status for m in selected]
        if getattr(args, "with_state", False):
            state = {
                "devices": statuses,
                "paused_by": response.get("paused_by"),
                "problem": problem,
            }
            print(json.dumps(state))
        elif args.json:
            print(json.dumps(statuses))
        elif problem:
            print(f"Paused: {problem}")
        elif statuses:
            _print_status(statuses, [mice.index(m) for m in selected])
        elif response.get("sleeping"):
            print("Paired MX mouse is asleep or out of range; wake it and retry.")
        elif response.get("scan_errors"):
            print("No reachable MX mouse; " + "; ".join(response["scan_errors"]))
        else:
            print("No supported MX mouse found (check pairing and Bluetooth connection).")
        return 0
    if args.command == "diagnose":
        result = _ipc_result({"op": "diagnose", "devices": [mice.index(m) for m in selected]})
        print(json.dumps(result["report"], indent=None if args.json else 2))
        return 0
    if not selected:
        print("No supported MX mouse found; wake it and retry.", file=sys.stderr)
        return 2
    device = selected[0]
    if not _supported_device(device):
        raise ValueError("unsupported Logitech device; writes are disabled for this mouse")
    if not device.writable:
        raise ValueError("mouse identity could not be verified; writes are disabled")
    if args.command == "dpi":
        settings = {"dpi": args.value}
    elif args.command == "smartshift":
        settings = {
            "smartshift": {
                k: v
                for k, v in (("mode", args.mode), ("threshold", args.threshold))
                if v is not None
            }
        }
    else:
        settings = {"invert": args.invert == "on"}
    result = _ipc_result(
        {
            "op": "set",
            "device": mice.index(device),
            "settings": settings,
            "selector": {"path": device.node.path, "index": device.index, "model": device.model},
        }
    )
    # The daemon returns readback in the same shape as direct mouse.status().
    status = result["status"]
    if args.json:
        print(json.dumps(status))
    elif args.command == "dpi":
        print(status["dpi"]["current"])
    elif args.command == "smartshift":
        print(f"{status['smartshift']['mode']} {status['smartshift']['threshold']}")
    else:
        print("inverted" if status["wheel"]["inverted"] else "normal")
    return 0


def _json_error(exc):
    message = str(exc)
    path = "config"
    if ": " in message:
        candidate, message = message.split(": ", 1)
        if candidate.startswith("config.") or candidate.startswith("action"):
            path = candidate.removeprefix("config.")
        else:
            message = str(exc)
    print(json.dumps({"ok": False, "errors": [{"path": path, "message": message}]}))
    return 1


def _new_command(args):
    try:
        command = args.command
        if command == "catalog":
            response = ipc.request_if_running({"op": "catalog"})
            result = response["catalog"] if response else action_catalog()
        elif command == "controls":
            # Without --mouse the list leaves out each mouse's resolved options,
            # which keeps the response bounded; --mouse N adds them for one mouse.
            selected = args.mouse
            if getattr(args, "device", None) is not None:
                raise ValueError("controls selects a mouse with --mouse N")
            message = {"op": "controls"}
            if selected is not None:
                message["device"] = selected
            response = ipc.request_if_running(message)
            if response is not None:
                if response.get("ok") is not True:
                    raise RuntimeError(response.get("error", "daemon rejected the request"))
                result = {"daemon": True, "devices": response["devices"]}
                if response.get("paused_by"):
                    result["paused_by"] = response["paused_by"]
                    result["problem"] = response.get("problem")
            else:
                mice = mouse.find_mice(include_unsupported=True)
                raw = ConfigFile().raw
                try:
                    if selected is not None and not 0 <= selected < len(mice):
                        raise ValueError(f"no mouse {selected}; found {len(mice)}")
                    devices = []
                    for i, device in enumerate(mice):
                        if not supported_device(device) or selected not in (None, i):
                            continue
                        status = dict(mouse.status(device), writable=device.writable)
                        diversion = Diversion(device) if device.writable else None
                        devices.append(
                            control_device(
                                status, i, diversion, raw, include_options=selected is not None
                            )
                        )
                    result = {"daemon": False, "devices": devices}
                finally:
                    hidpp.close_devices(mice)
        elif command == "test-action":
            action = _decode_action(read_config(sys.stdin))
            response = ipc.request_if_running({"op": "test_action", "action": action})
            if response is None:
                raise RuntimeError("test-action requires the running maestrod daemon")
            if response.get("ok") is not True:
                raise ConfigError(response.get("error", "daemon rejected action"))
            result = {"ok": True}
        else:
            operation = args.config_command
            message = {"op": f"config_{operation}"}
            if operation == "apply":
                message["config"] = _decode(read_config(sys.stdin))
            elif operation == "restore":
                message["name"] = args.name
            response = ipc.request_if_running(message)
            if response is not None:
                if response.get("ok") is not True:
                    raise ConfigError(response.get("error", "daemon rejected configuration"))
                if operation == "get":
                    result = response["config"]
                elif operation == "backups":
                    result = {"backups": response["backups"]}
                else:
                    result = {
                        "ok": True,
                        "backup": response["backup"],
                        "reloaded": response["reloaded"],
                    }
            else:
                config = ConfigFile()
                if config.error:
                    raise ConfigError(config.error)
                if operation == "get":
                    result = full_config(config.raw)
                elif operation == "backups":
                    result = {"backups": config.backups()}
                else:
                    backup = (
                        config.apply(message["config"])
                        if operation == "apply"
                        else config.restore(args.name)
                        if operation == "restore"
                        else config.undo()
                    )
                    result = {"ok": True, "backup": backup, "reloaded": False}
        print(json.dumps(result))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        return _json_error(exc)


def _release_buttons(args):
    """Explicitly undivert mouse controls Maestro may have left behind."""
    try:
        response = ipc.request_if_running({"op": "status"})
        if response is not None:
            if not isinstance(response, dict) or response.get("ok") is not True:
                raise RuntimeError("invalid daemon response")
            if response.get("paused_by"):
                raise RuntimeError(response.get("problem") or "the service is paused")
            mice = [_RemoteDevice(status) for status in response["devices"]]
            selected = _select(mice, args, all_by_default=True)
            selected = [m for m in selected if _supported_device(m)]
            if not selected:
                print("No supported MX mouse found; wake it and retry.", file=sys.stderr)
                return 2
            expected = _expected_selector(args, selected)
            results = []
            for m in selected:
                status = response["devices"][mice.index(m)]
                selector = device_selector(
                    status["path"], status["index"], status.get("model"), status.get("unit_key")
                )
                if expected is not None and selector != expected:
                    raise ValueError("device identity changed; read status and retry")
                result = _ipc_result(
                    {"op": "release_buttons", "device": mice.index(m), "selector": selector}
                )
                results.extend(result["devices"])
        else:
            results = _release_offline(args)
            if results is None:
                print(_absence(), file=sys.stderr)
                return 2
    except ValueError as e:
        print(f"maestro: {e}", file=sys.stderr)
        return 2
    except (hidpp.HidppError, hidpp.NoResponse, OSError, RuntimeError, KeyError) as e:
        print(f"maestro: {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "devices": results}))
        return 0
    for item in results:
        names = item["released"]
        where = f"{item['model']} (mouse {item['device']})"
        if names:
            print(f"Released the {', '.join(names)} on {where}.")
        else:
            print(f"Nothing to release on {where}.")
    return 0


def _expected_selector(args, selected):
    """The mouse identity the caller chose (``--selector``), checked before any write."""
    if args.selector is None:
        return None
    try:
        expected = json.loads(args.selector)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--selector: invalid JSON: {exc}") from exc
    if not valid_selector(expected):
        raise ValueError("--selector needs path, index, model and unit")
    if args.mouse is None or len(selected) != 1:
        raise ValueError("--selector needs --mouse N")
    return expected


def _release_offline(args):
    mice = mouse.find_mice(include_unsupported=True)
    try:
        selected = _select(mice, args, all_by_default=True)
        selected = [m for m in selected if _supported_device(m)]
        if not selected:
            return None
        expected = _expected_selector(args, selected)
        results = []
        for m in selected:
            if not getattr(m, "writable", True):
                raise ValueError("mouse identity could not be verified; writes are disabled")
            diversion = Diversion(m, ledger=DiversionLedger())
            if expected is not None and expected != device_selector(
                m.node.path, m.index, m.model, diversion.unit_key
            ):
                raise ValueError("device identity changed; read status and retry")
            try:
                # Rereads the live unit ID right before the first write.
                released = diversion.release_leftovers(
                    expected["unit"] if expected is not None else None,
                    required=expected is not None,
                )
            except IdentityChanged as exc:
                raise ValueError("device identity changed; read status and retry") from exc
            results.append({"device": mice.index(m), "model": m.model, "released": released})
        return results
    finally:
        hidpp.close_devices(mice)


def _decode_action(data):
    import json as json_module

    try:
        action = json_module.loads(data)
    except json_module.JSONDecodeError as exc:
        raise ConfigError(f"action: invalid JSON: {exc}") from exc
    # The daemon resolves automation ids against its live configuration.
    validate_action(action, "action")
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maestro", description="Settings for Logitech MX mice")
    _add_selector(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    p_status = sub.add_parser("status", help="show connected MX mice")
    _add_selector(p_status, suppress=True)
    p_status.add_argument("--all", action="store_true", help="also list unsupported Logitech mice")
    p_status.add_argument("--json", action="store_true")
    p_status.add_argument(
        "--with-state",
        action="store_true",
        help="JSON object with the mice and why the service is paused, if it is",
    )
    p_diagnose = sub.add_parser("diagnose", help="shareable, identifier-free device report")
    _add_selector(p_diagnose, suppress=True)
    p_diagnose.add_argument("--json", action="store_true")
    p_dpi = sub.add_parser("dpi", help="set pointer speed (DPI)")
    _add_selector(p_dpi, suppress=True)
    p_dpi.add_argument("value", type=int)
    p_dpi.add_argument(
        "--json", action="store_true", help="show full mouse status after the change"
    )
    p_ss = sub.add_parser("smartshift", help="wheel mode and auto-switch threshold")
    _add_selector(p_ss, suppress=True)
    p_ss.add_argument("--mode", choices=["ratchet", "freespin"])
    p_ss.add_argument("--threshold", type=int, help="1-254 wheel speed, 255 = never")
    p_ss.add_argument("--json", action="store_true", help="show full mouse status after the change")
    p_scroll = sub.add_parser("scroll", help="set scroll direction")
    _add_selector(p_scroll, suppress=True)
    p_scroll.add_argument("--invert", choices=["on", "off"], required=True)
    p_scroll.add_argument(
        "--json", action="store_true", help="show full mouse status after the change"
    )
    sub.add_parser("catalog", help="list curated actions").add_argument(
        "--json", action="store_true"
    )
    p_controls = sub.add_parser("controls", help="list mouse controls")
    p_controls.add_argument("--json", action="store_true")
    p_controls.add_argument(
        "--mouse",
        type=int,
        default=argparse.SUPPRESS,
        help="one mouse, including its resolved options",
    )
    p_release = sub.add_parser(
        "release-buttons",
        help="undivert buttons Maestro may have left diverted (explicit recovery)",
    )
    _add_selector(p_release, suppress=True)
    p_release.add_argument(
        "--selector",
        metavar="JSON",
        default=None,
        help="the mouse's selector from 'controls --json'; refuse if that mouse changed",
    )
    p_release.add_argument("--json", action="store_true")
    p_config = sub.add_parser("config", help="read or change the settings app configuration")
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("get")
    config_sub.add_parser("apply").add_argument("--stdin", action="store_true", required=True)
    config_sub.add_parser("backups").add_argument("--json", action="store_true")
    config_sub.add_parser("restore").add_argument("name")
    config_sub.add_parser("undo")
    sub.add_parser("test-action", help="run one action through the daemon").add_argument(
        "--stdin", action="store_true", required=True
    )
    args = parser.parse_args(argv)

    if args.command in ("catalog", "controls", "config", "test-action"):
        return _new_command(args)
    if args.command == "release-buttons":
        return _release_buttons(args)

    if args.command == "smartshift" and args.mode is None and args.threshold is None:
        parser.error("give --mode and/or --threshold")
    try:
        response = ipc.request_if_running({"op": "status"})
        if response is not None:
            return _from_daemon(args, response)
    except ValueError as e:
        print(f"maestro: {e}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, KeyError, TypeError) as e:
        print(f"maestro: daemon request failed: {e}", file=sys.stderr)
        return 1

    # One discovery order and one --mouse numbering for every command.
    mice = mouse.find_mice(include_unsupported=True)
    try:
        selected = _select(mice, args, all_by_default=args.command in ("status", "diagnose"))
        if args.command == "status":
            if args.mouse is None and args.device is None and not args.all:
                selected = [m for m in selected if _supported_device(m)]
            statuses = [mouse.status(m) for m in selected]
            if args.with_state:
                print(json.dumps({"devices": statuses, "paused_by": None, "problem": None}))
            elif args.json:
                print(json.dumps(statuses))
            elif statuses:
                numbers = {id(m): i for i, m in enumerate(mice)}
                _print_status(statuses, [numbers[id(m)] for m in selected])
            else:
                print(_absence())
            return 0

        if args.command == "diagnose":
            report = {
                "schema": 1,
                "devices": [mouse.diagnose(m) for m in selected],
                "sleeping": [
                    {
                        "connection": s.connection,
                        "wpid": f"{s.wpid:04X}" if s.wpid else None,
                        "slot": s.index if s.connection != "bluetooth" else None,
                    }
                    for s in mouse.last_scan.sleeping
                ],
            }
            print(json.dumps(report, indent=None if args.json else 2))
            return 0

        if not selected:
            print(_absence(), file=sys.stderr)
            return 2
        m = selected[0]
        if not _supported_device(m):
            print(
                "maestro: unsupported Logitech device; writes are disabled for this mouse",
                file=sys.stderr,
            )
            return 2
        if not getattr(m, "writable", True):
            print(
                "maestro: mouse identity could not be verified; writes are disabled",
                file=sys.stderr,
            )
            return 2
        # Read the unit ID now; each write below reads it again and must match.
        if guard_device(m).expected is None:
            print(f"maestro: {IDENTITY_PROBLEM}", file=sys.stderr)
            return 2
        if args.command == "dpi":
            result = str(mouse.set_dpi(m, args.value))
        elif args.command == "smartshift":
            if args.mode is None and args.threshold is None:
                parser.error("give --mode and/or --threshold")
            s = mouse.set_smartshift(m, args.mode, args.threshold)
            result = f"{s.mode} {s.threshold}"
        else:
            w = mouse.set_wheel(m, inverted=args.invert == "on")
            result = "inverted" if w.inverted else "normal"
        print(json.dumps(mouse.status(m)) if args.json else result)
        return 0
    except Unidentified:
        print(f"maestro: {IDENTITY_PROBLEM}", file=sys.stderr)
        return 2
    except IdentityChanged:
        print("maestro: device identity changed; read status and retry", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"maestro: {e}", file=sys.stderr)
        return 2
    except (hidpp.HidppError, hidpp.NoResponse) as e:
        print(f"maestro: {e}", file=sys.stderr)
        return 1
    finally:
        hidpp.close_devices(mice)


if __name__ == "__main__":
    sys.exit(main())
