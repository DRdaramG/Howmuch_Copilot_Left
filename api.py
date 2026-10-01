"""Quota adapters for supported AI services."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

TIMEOUT = 15


@dataclass
class QuotaWindow:
    label: str
    used_percent: float
    used: float | None = None
    total: float | None = None
    unit: str = ""
    resets_at: str | None = None


@dataclass
class QuotaResult:
    provider: str
    windows: list[QuotaWindow] = field(default_factory=list)
    error: str | None = None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _window(
    label: str,
    *,
    used: Any = None,
    total: Any = None,
    percent: Any = None,
    remaining: Any = None,
    unit: str = "",
    reset: Any = None,
) -> QuotaWindow | None:
    used_num, total_num = _number(used), _number(total)
    remaining_num = _number(remaining)
    percent_num = _number(percent)
    if used_num is None and total_num is not None and remaining_num is not None:
        used_num = total_num - remaining_num
    if percent_num is None and used_num is not None and total_num:
        percent_num = used_num / total_num * 100
    if percent_num is None:
        return None
    return QuotaWindow(
        label=label,
        used_percent=max(0.0, min(100.0, percent_num)),
        used=used_num,
        total=total_num,
        unit=unit,
        resets_at=str(reset) if reset else None,
    )


def _request_json(
    method: str, url: str, token: str | None = None, headers: dict | None = None
) -> dict:
    request_headers = {"Accept": "application/json", **(headers or {})}
    if token:
        request_headers.setdefault("Authorization", f"******")
    response = requests.request(
        method, url, headers=request_headers, timeout=TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("API returned a non-object response")
    return payload


def _secret(settings: dict, env_name: str) -> str | None:
    value = settings.get("token") or os.environ.get(env_name)
    return str(value) if value else None


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.expanduser().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def fetch_copilot(settings: dict) -> QuotaResult:
    token = _secret(settings, "COPILOT_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        return QuotaResult("Copilot", error="set COPILOT_TOKEN")
    data = _request_json(
        "GET",
        settings.get("url", "https://api.github.com/copilot_internal/user"),
        token,
    )
    snapshots = data.get("quota_snapshots") or {}
    quota = (
        snapshots.get("ai_credits")
        or snapshots.get("premium_interactions")
        or data.get("ai_credits")
        or {}
    )
    if not isinstance(quota, dict):
        return QuotaResult("Copilot", error="AI credit quota is absent")
    total = quota.get("entitlement", quota.get("limit", quota.get("total")))
    window = _window(
        "AI credits",
        used=quota.get("used", quota.get("usage")),
        total=total,
        remaining=quota.get("quota_remaining", quota.get("remaining")),
        percent=quota.get("percent_used"),
        unit="credits",
        reset=quota.get("reset_at", quota.get("resets_at")),
    )
    return QuotaResult("Copilot", [window] if window else [], None if window else "unknown AI credit format")


def fetch_codex(settings: dict) -> QuotaResult:
    auth_path = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "auth.json"
    auth = _read_json(auth_path)
    tokens = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else {}
    token = _secret(settings, "CODEX_ACCESS_TOKEN") or tokens.get("access_token")
    if not token:
        return QuotaResult("Codex", error="run `codex login` or set CODEX_ACCESS_TOKEN")
    account_id = settings.get("account_id") or tokens.get("account_id")
    headers = {"ChatGPT-Account-Id": str(account_id)} if account_id else {}
    data = _request_json(
        "GET",
        settings.get("url", "https://chatgpt.com/backend-api/wham/usage"),
        token,
        headers,
    )
    rate_limit = data.get("rate_limit") or {}
    windows = []
    for name, value in (
        ("session", rate_limit.get("primary_window")),
        ("weekly", rate_limit.get("secondary_window")),
    ):
        if not isinstance(value, dict):
            continue
        label = name
        seconds = _number(value.get("limit_window_seconds"))
        if seconds and seconds >= 3 * 86400:
            label = "weekly"
        window = _window(
            label,
            percent=value.get("used_percent"),
            reset=value.get("reset_at"),
        )
        if window:
            windows.append(window)
    return QuotaResult("Codex", windows, None if windows else "unknown usage format")


def fetch_claude(settings: dict) -> QuotaResult:
    credentials = _read_json(Path("~/.claude/.credentials.json"))
    oauth = credentials.get("claudeAiOauth") if isinstance(credentials.get("claudeAiOauth"), dict) else {}
    token = _secret(settings, "CLAUDE_ACCESS_TOKEN") or oauth.get("accessToken")
    if not token:
        return QuotaResult("Claude", error="set CLAUDE_ACCESS_TOKEN or log in with Claude Code")
    data = _request_json(
        "GET",
        settings.get("url", "https://api.anthropic.com/api/oauth/usage"),
        token,
        {"anthropic-beta": "oauth-2025-04-20"},
    )
    windows = []
    limits = data.get("limits")
    if isinstance(limits, list):
        for value in limits:
            if not isinstance(value, dict):
                continue
            kind = value.get("kind", "quota")
            label = {"session": "5h", "weekly_all": "7d"}.get(kind, str(kind))
            window = _window(label, percent=value.get("percent"), reset=value.get("resets_at"))
            if window:
                windows.append(window)
    else:
        for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
            value = data.get(key)
            if isinstance(value, dict):
                utilization = _number(value.get("utilization"))
                if utilization is not None and utilization <= 1:
                    utilization *= 100
                window = _window(label, percent=utilization, reset=value.get("resets_at"))
                if window:
                    windows.append(window)
    return QuotaResult("Claude", windows, None if windows else "unknown usage format")


def fetch_nanogpt(settings: dict) -> QuotaResult:
    token = _secret(settings, "NANOGPT_API_KEY")
    if not token:
        return QuotaResult("NanoGPT", error="set NANOGPT_API_KEY")
    data = _request_json(
        "GET",
        settings.get("url", "https://nano-gpt.com/api/subscription/v1/usage"),
        headers={"x-api-key": token},
    )
    windows = []
    for key, label, unit in (
        ("dailyInputTokens", "daily", "tokens"),
        ("weeklyInputTokens", "weekly", "tokens"),
        ("dailyImages", "daily images", "images"),
    ):
        value = data.get(key)
        if not isinstance(value, dict):
            continue
        percent = _number(value.get("percentUsed"))
        if percent is not None and percent <= 1:
            percent *= 100
        window = _window(
            label,
            used=value.get("used"),
            total=(data.get("limits") or {}).get(key),
            percent=percent,
            remaining=value.get("remaining"),
            unit=unit,
            reset=value.get("resetAt"),
        )
        if window:
            windows.append(window)
    return QuotaResult("NanoGPT", windows, None if windows else "subscription is inactive or unavailable")


def fetch_ollama(settings: dict) -> QuotaResult:
    base = str(settings.get("url", "http://localhost:11434")).rstrip("/")
    data = _request_json("GET", f"{base}/api/ps")
    count = len(data.get("models", [])) if isinstance(data.get("models"), list) else 0
    return QuotaResult(
        "Ollama",
        [QuotaWindow("local (unlimited)", 0, count, count, "loaded models")],
    )


def fetch_devpass(settings: dict) -> QuotaResult:
    token = _secret(settings, "DEVPASS_API_KEY")
    if not token:
        return QuotaResult("DevPass", error="set DEVPASS_API_KEY")
    payload = _request_json(
        "GET", settings.get("url", "https://api.llmgateway.io/v1/key"), token
    )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    windows = []
    for label, used_key, limit_key, reset_key in (
        ("credits", "devPlanCreditsUsed", "devPlanCreditsLimit", None),
        (
            "premium weekly",
            "devPlanPremiumCreditsUsed",
            "devPlanPremiumWeeklyLimit",
            "devPlanPremiumWeekResetsAt",
        ),
    ):
        window = _window(
            label,
            used=data.get(used_key),
            total=data.get(limit_key),
            unit="credits",
            reset=data.get(reset_key) if reset_key else None,
        )
        if window:
            windows.append(window)
    if not windows:
        window = _window("usage", used=data.get("usage"), total=data.get("limit"))
        if window:
            windows.append(window)
    return QuotaResult("DevPass", windows, None if windows else "unknown usage format")


PROVIDERS: dict[str, Callable[[dict], QuotaResult]] = {
    "copilot": fetch_copilot,
    "codex": fetch_codex,
    "claude": fetch_claude,
    "nanogpt": fetch_nanogpt,
    "ollama": fetch_ollama,
    "devpass": fetch_devpass,
}


def fetch_provider(name: str, settings: dict) -> QuotaResult:
    fetcher = PROVIDERS.get(name)
    if fetcher is None:
        return QuotaResult(name, error="unsupported provider")
    try:
        return fetcher(settings)
    except requests.RequestException as exc:
        return QuotaResult(name.title(), error=f"request failed: {exc}")
    except (TypeError, ValueError, KeyError) as exc:
        return QuotaResult(name.title(), error=f"invalid response: {exc}")
