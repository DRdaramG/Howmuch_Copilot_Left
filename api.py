"""Quota adapters for supported AI services."""

from __future__ import annotations

import json
import os
import tempfile
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
    plan: str | None = None


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
        request_headers.setdefault("Authorization", "Bearer" + " " + token)
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


def _refresh_codex_auth(path: Path, auth: dict) -> str:
    tokens = auth.get("tokens")
    refresh_token = tokens.get("refresh_token") if isinstance(tokens, dict) else None
    if not refresh_token:
        raise ValueError("Codex login expired; run `codex login`")
    response = requests.post(
        "https://auth.openai.com/oauth/token",
        json={
            "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "openid profile email",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    refreshed = response.json()
    access_token = refreshed.get("access_token")
    if not access_token:
        raise ValueError("Codex token refresh returned no access token")
    latest = _read_json(path)
    latest_tokens = latest.get("tokens") if isinstance(latest.get("tokens"), dict) else {}
    if latest_tokens.get("refresh_token") not in (None, refresh_token):
        latest_access_token = latest_tokens.get("access_token")
        if latest_access_token:
            return str(latest_access_token)
    tokens["access_token"] = access_token
    for key in ("refresh_token", "id_token"):
        if refreshed.get(key):
            tokens[key] = refreshed[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        json.dump(auth, temporary, indent=2)
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(path)
    return str(access_token)


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
    url = settings.get("url", "https://chatgpt.com/backend-api/wham/usage")
    try:
        data = _request_json("GET", url, token, headers)
    except requests.HTTPError as exc:
        if exc.response is None or exc.response.status_code not in (401, 403):
            raise
        token = _refresh_codex_auth(auth_path, auth)
        data = _request_json("GET", url, token, headers)
    windows = _codex_rate_windows(data.get("rate_limit"), "Codex")
    windows.extend(
        _codex_rate_windows(data.get("code_review_rate_limit"), "code review")
    )
    additional = data.get("additional_rate_limits")
    if isinstance(additional, list):
        for value in additional:
            if isinstance(value, dict):
                label = str(value.get("limit_name") or "additional")
                windows.extend(_codex_rate_windows(value.get("rate_limit"), label))
    chatpass = data.get("chatpass")
    if isinstance(chatpass, dict) and isinstance(chatpass.get("windows"), list):
        for value in chatpass["windows"]:
            window = _codex_window(value, "ChatGPT")
            if window:
                windows.append(window)
    plan = str(data["plan_type"]) if data.get("plan_type") else None
    return QuotaResult(
        "Codex", windows, None if windows else "unknown usage format", plan
    )


def _codex_rate_windows(value: Any, prefix: str) -> list[QuotaWindow]:
    if not isinstance(value, dict):
        return []
    windows = []
    for candidate in (value.get("primary_window"), value.get("secondary_window")):
        window = _codex_window(candidate, prefix)
        if window:
            windows.append(window)
    return windows


def _codex_window(value: Any, prefix: str) -> QuotaWindow | None:
    if not isinstance(value, dict):
        return None
    seconds = _number(value.get("limit_window_seconds"))
    period = "weekly" if seconds and seconds >= 3 * 86400 else "5h"
    return _window(
        f"{prefix} {period}",
        percent=value.get("used_percent"),
        reset=value.get("reset_at"),
    )


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
    labels = set()
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        value = data.get(key)
        if isinstance(value, dict):
            window = _window(
                label,
                percent=value.get("utilization"),
                reset=value.get("resets_at"),
            )
            if window:
                windows.append(window)
                labels.add(label)
    for key, label in (
        ("seven_day_opus", "7d Opus"),
        ("seven_day_sonnet", "7d Sonnet"),
    ):
        value = data.get(key)
        if isinstance(value, dict) and _number(value.get("utilization")):
            window = _window(
                label,
                percent=value.get("utilization"),
                reset=value.get("resets_at"),
            )
            if window:
                windows.append(window)
                labels.add(label)
    limits = data.get("limits")
    if isinstance(limits, list):
        for value in limits:
            if not isinstance(value, dict):
                continue
            kind = value.get("kind", "quota")
            label = {
                "session": "5h",
                "weekly_all": "7d",
                "weekly_model": "7d model",
                "weekly_scoped": "7d scoped",
            }.get(kind, str(kind))
            percent = _number(value.get("percent"))
            if label in labels or not percent:
                continue
            window = _window(label, percent=value.get("percent"), reset=value.get("resets_at"))
            if window:
                windows.append(window)
                labels.add(label)
    plan = oauth.get("subscriptionType")
    return QuotaResult(
        "Claude",
        windows,
        None if windows else "unknown usage format",
        str(plan) if plan else None,
    )


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
    return _fetch_cloud_usage(
        "Ollama",
        settings,
        "OLLAMA_API_KEY",
        "OLLAMA_USAGE_URL",
    )


def fetch_antigravity(settings: dict) -> QuotaResult:
    return _fetch_cloud_usage(
        "Antigravity",
        settings,
        "ANTIGRAVITY_ACCESS_TOKEN",
        "ANTIGRAVITY_USAGE_URL",
    )


def _fetch_cloud_usage(
    provider: str,
    settings: dict,
    token_env: str,
    url_env: str,
) -> QuotaResult:
    token = _secret(settings, token_env)
    url = settings.get("url") or os.environ.get(url_env)
    if not token:
        return QuotaResult(provider, error=f"set {token_env}")
    if not url:
        return QuotaResult(
            provider,
            error=f"set {url_env}; this service has no documented quota endpoint",
        )
    data = _request_json("GET", str(url), token)
    plan = _plan_name(data)
    windows = _quota_windows(data)
    return QuotaResult(
        provider,
        windows,
        None if windows else "usage endpoint returned no recognized quotas",
        plan,
    )


def _plan_name(data: dict) -> str | None:
    plan = data.get("plan") or data.get("tier") or data.get("current_plan")
    subscription = data.get("subscription")
    if not plan and isinstance(subscription, dict):
        plan = subscription.get("plan") or subscription.get("tier") or subscription.get("name")
    if isinstance(plan, dict):
        plan = plan.get("name") or plan.get("id") or plan.get("slug")
    return str(plan) if plan else None


def _quota_windows(data: dict) -> list[QuotaWindow]:
    containers: list[tuple[str, Any]] = []
    for key in ("windows", "quotas", "limits", "usage"):
        value = data.get(key)
        if isinstance(value, (dict, list)):
            containers.append((key, value))
    for key in (
        "five_hour",
        "fiveHour",
        "session",
        "daily",
        "weekly",
        "seven_day",
        "sevenDay",
        "monthly",
    ):
        if isinstance(data.get(key), dict):
            containers.append((key, data[key]))

    candidates: list[tuple[str, dict]] = []
    for container_name, container in containers:
        if isinstance(container, list):
            for index, value in enumerate(container):
                if isinstance(value, dict):
                    candidates.append((str(value.get("label") or value.get("name") or index), value))
        elif any(
            key in container
            for key in ("used", "usage", "total", "limit", "remaining", "percent", "percent_used", "utilization")
        ):
            candidates.append((container_name, container))
        else:
            candidates.extend(
                (str(name), value)
                for name, value in container.items()
                if isinstance(value, dict)
            )

    windows = []
    for fallback_label, value in candidates:
        label = str(value.get("label") or value.get("name") or fallback_label)
        label = {
            "five_hour": "5h",
            "fiveHour": "5h",
            "seven_day": "7d",
            "sevenDay": "7d",
        }.get(label, label)
        percent = value.get(
            "percent_used",
            value.get("percentUsed", value.get("percent", value.get("utilization"))),
        )
        if "utilization" in value:
            utilization = _number(percent)
            if utilization is not None and utilization <= 1:
                percent = utilization * 100
        window = _window(
            label,
            used=value.get("used", value.get("usage")),
            total=value.get("total", value.get("limit", value.get("entitlement"))),
            remaining=value.get("remaining", value.get("quota_remaining")),
            percent=percent,
            unit=str(value.get("unit", "")),
            reset=value.get(
                "resets_at",
                value.get("reset_at", value.get("resetAt", value.get("next_reset"))),
            ),
        )
        if window:
            windows.append(window)
    return windows


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
    "antigravity": fetch_antigravity,
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
