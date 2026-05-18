from __future__ import annotations

import argparse
import sys

from .telegram.common import DEFAULT_CONFIG_PATH, SingleInstanceLock, bot_lock_path, load_config
from .telegram.runtime import run_loop, run_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scheduled Telegram sender for daily DeFi/Core research digests.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Telegram bot config JSON.")
    parser.add_argument("--once", action="store_true", help="Run one collection/send cycle and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print messages instead of sending to Telegram.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    lock = SingleInstanceLock(bot_lock_path(config))
    if not lock.acquire():
        print(f"Another Telegram digest bot instance is already running. Lock: {bot_lock_path(config)}", file=sys.stderr)
        return 0
    try:
        if args.once:
            run_once(config, dry_run=args.dry_run)
        else:
            run_loop(config, dry_run=args.dry_run)
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
