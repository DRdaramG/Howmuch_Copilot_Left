"""Linux CLI entry point for the AI quota monitor."""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import signal
import sys
import termios
import time
import tty
import unicodedata
from dataclasses import asdict
from datetime import datetime, tzinfo

import api
import config

BAR_WIDTH = 10
RESET = "\033[0m"
DIM = "\033[90m"
PROVIDER_COLORS = {
    "copilot": "\033[38;5;212m",
    "codex": "\033[38;5;40m",
    "claude": "\033[38;5;208m",
    "nanogpt": "\033[38;5;45m",
    "ollama": "\033[38;5;255m",
    "antigravity": "\033[38;5;69m",
    "devpass": "\033[38;5;141m",
}


def progress_bar(
    percent: float, width: int = BAR_WIDTH, color: str | None = None
) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = round(percent * width / 100)
    empty = width - filled
    if color:
        return f"{color}{'█' * filled}{DIM}{'░' * empty}{RESET}"
    return "█" * filled + "░" * empty


def display_width(text: str) -> int:
    clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    width = 0
    for ch in clean:
        if unicodedata.east_asian_width(ch) in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def pad(text: str, width: int, align: str = "left") -> str:
    dw = display_width(text)
    spaces = max(0, width - dw)
    if align == "right":
        return " " * spaces + text
    return text + " " * spaces


def format_reset(value: str, local_timezone: tzinfo | None = None) -> str:
    try:
        timestamp = float(value)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        if abs(timestamp) >= 100_000_000_000:
            timestamp /= 1000
        try:
            parsed = datetime.fromtimestamp(
                timestamp, tz=datetime.now().astimezone().tzinfo
            )
        except (ValueError, OverflowError, OSError):
            return value
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    parsed = parsed.astimezone(local_timezone)
    return parsed.strftime("%Y-%m-%d %H:%M")


def render(results: list[api.QuotaResult], *, color: bool = False) -> str:
    header_title = f"AI quota usage · {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %Z}"
    lines = [header_title]
    if not results:
        lines.append("No active providers enabled.")
        return "\n".join(lines)

    headers = ["Service", "Quota", "Usage", "Details", "Reset"]
    rows: list[dict[str, str]] = []

    for result in results:
        service_name = result.provider
        if result.plan:
            service_name += f" ({result.plan})"
        provider_key = result.provider.lower()
        theme = PROVIDER_COLORS.get(provider_key) if color else None

        if result.error:
            rows.append({
                "service": service_name,
                "provider": result.provider,
                "quota": f"unavailable: {result.error}",
                "usage": "-",
                "details": "-",
                "reset": "-",
                "theme": theme or "",
            })
            continue

        if not result.windows:
            rows.append({
                "service": service_name,
                "provider": result.provider,
                "quota": "no quota reported",
                "usage": "-",
                "details": "-",
                "reset": "-",
                "theme": theme or "",
            })
            continue

        for window in result.windows:
            details = "-"
            if window.used is not None and window.total is not None:
                details = f"{window.used:g}/{window.total:g} {window.unit}".rstrip()
            reset_val = format_reset(window.resets_at) if window.resets_at else "-"
            pct = window.used_percent
            bar = progress_bar(pct, color=theme if color else None)
            usage_str = f"{bar} ({pct:.0f}%)"
            rows.append({
                "service": service_name,
                "provider": result.provider,
                "quota": window.label,
                "usage": usage_str,
                "details": details,
                "reset": reset_val,
                "theme": theme or "",
            })

    if not rows:
        lines.append("No quota data to display.")
        return "\n".join(lines)

    col_widths = [display_width(h) for h in headers]
    for r in rows:
        col_widths[0] = max(col_widths[0], display_width(r["service"]))
        col_widths[1] = max(col_widths[1], display_width(r["quota"]))
        col_widths[2] = max(col_widths[2], display_width(r["usage"]))
        col_widths[3] = max(col_widths[3], display_width(r["details"]))
        col_widths[4] = max(col_widths[4], display_width(r["reset"]))

    def sep(left: str, mid: str, right: str, cross: str) -> str:
        return left + cross.join("─" * (w + 2) for w in col_widths) + right

    lines.append(sep("┌", "─", "┐", "┬"))
    lines.append("│ " + " │ ".join(pad(h, w) for h, w in zip(headers, col_widths)) + " │")
    lines.append(sep("├", "─", "┤", "┼"))

    prev_service = None
    for i, r in enumerate(rows):
        serv = r["service"]
        theme = r["theme"]
        if prev_service is not None and serv != prev_service:
            lines.append(sep("├", "─", "┤", "┼"))
        prev_service = serv

        is_first = (i == 0 or rows[i - 1]["service"] != serv)
        display_service = serv if is_first else ""
        if display_service and theme:
            display_service = f"{theme}{display_service}{RESET}"

        display_quota = r["quota"]
        if theme and not r["quota"].startswith("unavailable"):
            display_quota = f"{theme}{display_quota}{RESET}"

        cells = [
            pad(display_service, col_widths[0]),
            pad(display_quota, col_widths[1]),
            pad(r["usage"], col_widths[2]),
            pad(r["details"], col_widths[3]),
            pad(r["reset"], col_widths[4]),
        ]
        lines.append("│ " + " │ ".join(cells) + " │")

    lines.append(sep("└", "─", "┘", "┴"))
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
    previous_handlers = {}
    if interactive:
        def terminate(received: int, _frame: object) -> None:
            raise SystemExit(128 + received)

        for signal_number in (signal.SIGTERM, signal.SIGHUP):
            previous_handlers[signal_number] = signal.getsignal(signal_number)
            signal.signal(signal_number, terminate)
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
        for signal_number, handler in previous_handlers.items():
            signal.signal(signal_number, handler)
        if interactive:
            print("\033[?1049l", end="", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
