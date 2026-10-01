"""Linux CLI entry point for the AI quota monitor."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime

import api
import config

BAR_WIDTH = 10


def progress_bar(percent: float) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(percent * BAR_WIDTH / 100)
    return "■" * filled + "□" * (BAR_WIDTH - filled)


def render(results: list[api.QuotaResult]) -> str:
    lines = [f"AI quota usage · {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}"]
    for result in results:
        if result.error:
            lines.append(f"{result.provider:<12} unavailable: {result.error}")
            continue
        if not result.windows:
            lines.append(f"{result.provider:<12} no quota reported")
            continue
        for window in result.windows:
            label = f"{result.provider} {window.label}".strip()
            suffix = f"{progress_bar(window.used_percent)} ({window.used_percent:.0f}%)"
            if window.used is not None and window.total is not None:
                suffix += f"  {window.used:g}/{window.total:g} {window.unit}".rstrip()
            if window.resets_at:
                suffix += f"  resets {window.resets_at}"
            lines.append(f"{label:<24} {suffix}")
    return "\n".join(lines)


def collect(settings: dict) -> list[api.QuotaResult]:
    providers = settings.get("providers", {})
    return [
        api.fetch_provider(name, provider_settings)
        for name, provider_settings in providers.items()
        if provider_settings.get("enabled", False)
    ]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor AI service quotas in a Linux terminal.")
    parser.add_argument("--once", action="store_true", help="print once instead of refreshing")
    parser.add_argument("--json", action="store_true", help="emit JSON (implies --once)")
    parser.add_argument("--no-clear", action="store_true", help="do not clear the terminal")
    parser.add_argument("--interval", type=int, help="refresh interval in seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = config.load()
    interval = args.interval or int(settings.get("refresh_interval_seconds", 60))
    if interval < 1:
        print("error: refresh interval must be at least one second", file=sys.stderr)
        return 2

    try:
        while True:
            results = collect(settings)
            if args.json:
                print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
            else:
                if not args.once and not args.no_clear and sys.stdout.isatty():
                    print("\033[2J\033[H", end="")
                print(render(results), flush=True)
            if args.once or args.json:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
