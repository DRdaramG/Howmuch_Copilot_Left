"""Linux CLI entry point for the AI quota monitor."""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import termios
import time
import tty
from dataclasses import asdict
from datetime import datetime, tzinfo

import api
import config

BAR_WIDTH = 10
RESET = "\033[0m"
PROVIDER_COLORS = {
    "copilot": "\033[38;5;212m",
    "codex": "\033[38;5;40m",
    "claude": "\033[38;5;208m",
    "nanogpt": "\033[38;5;45m",
    "ollama": "\033[38;5;255m",
    "antigravity": "\033[38;5;69m",
    "devpass": "\033[38;5;141m",
}


def progress_bar(percent: float) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(percent * BAR_WIDTH / 100)
    return "■" * filled + "□" * (BAR_WIDTH - filled)


def format_reset(value: str, local_timezone: tzinfo | None = None) -> str:
    try:
        timestamp = float(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        parsed = datetime.fromtimestamp(timestamp, tz=datetime.now().astimezone().tzinfo)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    parsed = parsed.astimezone(local_timezone)
    return parsed.strftime("%Y-%m-%d %H:%M")


def _themed(line: str, provider: str, color: bool) -> str:
    theme = PROVIDER_COLORS.get(provider.lower()) if color else None
    return f"{theme}{line}{RESET}" if theme else line


def render(results: list[api.QuotaResult], *, color: bool = False) -> str:
    lines = [f"AI quota usage · {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}"]
    for result in results:
        provider = result.provider
        if result.plan:
            provider += f" ({result.plan})"
        if result.error:
            lines.append(
                _themed(
                    f"{provider:<12} unavailable: {result.error}",
                    result.provider,
                    color,
                )
            )
            continue
        if not result.windows:
            lines.append(
                _themed(
                    f"{provider:<12} no quota reported", result.provider, color
                )
            )
            continue
        for window in result.windows:
            label = f"{provider} {window.label}".strip()
            suffix = f"{progress_bar(window.used_percent)} ({window.used_percent:.0f}%)"
            if window.used is not None and window.total is not None:
                suffix += f"  {window.used:g}/{window.total:g} {window.unit}".rstrip()
            if window.resets_at:
                suffix += f"  resets {format_reset(window.resets_at)}"
            lines.append(
                _themed(f"{label:<24} {suffix}", result.provider, color)
            )
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


def wait_for_refresh(seconds: int) -> bool:
    if not sys.stdin.isatty():
        time.sleep(seconds)
        return False
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        updated = termios.tcgetattr(descriptor)
        updated[0] &= ~termios.IXON
        termios.tcsetattr(descriptor, termios.TCSADRAIN, updated)
        ready, _, _ = select.select([sys.stdin], [], [], seconds)
        return bool(ready and os.read(descriptor, 1) == b"\x13")
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = config.load()
    interval = args.interval or int(settings.get("refresh_interval_seconds", 60))
    if interval < 1:
        print("error: refresh interval must be at least one second", file=sys.stderr)
        return 2

    interactive = (
        not args.once
        and not args.json
        and not args.no_clear
        and sys.stdout.isatty()
    )
    if interactive:
        print("\033[?1049h", end="", flush=True)
    try:
        while True:
            results = collect(settings)
            if args.json:
                print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
            else:
                if interactive:
                    print("\033[H\033[2J", end="")
                use_color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
                print(render(results, color=use_color), flush=True)
                if not args.once and sys.stdin.isatty():
                    print("\nCtrl+S: 설정 메뉴", flush=True)
            if args.once or args.json:
                return 0
            if wait_for_refresh(interval):
                settings = config.menu()
                interval = args.interval or int(
                    settings.get("refresh_interval_seconds", 60)
                )
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 0
    finally:
        if interactive:
            print("\033[?1049l", end="", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
