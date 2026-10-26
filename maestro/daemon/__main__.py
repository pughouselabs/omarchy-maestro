"""maestrod entry point and small diagnostic IPC client."""

import argparse
import json
import logging
import sys

from maestro import hidpp

from .config import ConfigError, ConfigFile
from .ipc import request
from .service import Daemon


def main(argv=None):
    parser = argparse.ArgumentParser(description="Persistent Maestro mouse settings and actions")
    parser.add_argument("--config", help="config.json path (default: XDG config directory)")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate configuration without opening hardware",
    )
    parser.add_argument(
        "--request", metavar="JSON", help="send one JSON request to an already running daemon"
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s"
    )
    try:
        if args.request is not None:
            result = request(json.loads(args.request))
            print(json.dumps(result, indent=2))
            return 0 if result.get("ok") else 1
        config = ConfigFile(args.config)
        if config.error:
            raise ConfigError(config.error)
        if args.check_config:
            print(f"Configuration valid: {config.path}")
            return 0
        Daemon(config).run()
        return 0
    except (OSError, ValueError, RuntimeError, hidpp.HidppError, hidpp.NoResponse) as exc:
        print(f"maestrod: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
