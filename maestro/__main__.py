"""maestro: Logitech MX mouse settings and shareable diagnostics.

  maestro status [--all] [--json]
  maestro diagnose [--json]
  maestro dpi <value> [--json]
  maestro smartshift [--mode ratchet|freespin] [--threshold 1-255] [--json]
  maestro scroll --invert on|off [--json]

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
from .daemon.catalog import control_device
from .daemon.config import ConfigError, ConfigFile, _decode, full_config, validate_action
from .daemon.events import Diversion, supported_device


def _print_status(statuses: list[dict], numbers: list[int]) -> None:
    for n, s in zip(numbers, statuses, strict=False):
        where = f"receiver slot {s['index']}" if s["receiver"] else "Bluetooth"
        print(
            f"[{n}] {s['name']}  ({s['path']}, {where})"
            f"{'  unsupported' if not s.get('supported', True) else ''}"
        )
        if not s.get("supported", True):
            continue
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


_DAEMON_FIELDS = {"writable", "online", "profile", "errors", "diverted_controls", "thumb_diverted"}


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
    mice = [_RemoteDevice(status) for status in response["devices"]]
    selected = _select(mice, args, all_by_default=args.command in ("status", "diagnose"))
    if args.command == "status":
        if args.mouse is None and args.device is None and not args.all:
            selected = [m for m in selected if _supported_device(m)]
        statuses = [m.status for m in selected]
        if args.json:
            print(json.dumps(statuses))
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
            response = ipc.request_if_running({"op": "controls"})
            if response is not None:
                result = {"daemon": True, "devices": response["devices"]}
            else:
                mice = mouse.find_mice(include_unsupported=True)
                raw = ConfigFile().raw
                try:
                    devices = []
                    for i, device in enumerate(mice):
                        if not supported_device(device):
                            continue
                        status = dict(mouse.status(device), writable=device.writable)
                        diversion = Diversion(device) if device.writable else None
                        devices.append(control_device(status, i, diversion, raw))
                    result = {"daemon": False, "devices": devices}
                finally:
                    hidpp.close_devices(mice)
        elif command == "test-action":
            action = _decode_action(sys.stdin.read())
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
                message["config"] = _decode(sys.stdin.read())
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
    sub.add_parser("controls", help="list mouse controls").add_argument(
        "--json", action="store_true"
    )
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
            if args.json:
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
