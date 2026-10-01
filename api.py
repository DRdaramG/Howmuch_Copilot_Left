"""Quota adapters for supported AI services."""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

TIMEOUT = 15
AGY_TIMEOUT = 45
CACHE_TTL = 300
COOLDOWN_SECONDS = 300
OLLAMA_USAGE_URL = "https://ollama.com/api/usage"
OLLAMA_ACCOUNT_URL = "https://ollama.com/api/me"
OLLAMA_SETTINGS_URL = "https://ollama.com/settings"

CACHE_DIR = (
    Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    / "howmuch-left"
)
CACHE_FILE = CACHE_DIR / "cache.json"

_MEMORY_CACHE: dict[str, dict] = {}
_COOLDOWNS: dict[str, float] = {}




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


def _clean_plan(plan: str | None) -> str | None:
    if not plan:
        return None
    cleaned = re.sub(r"\s*\(?\s*cached\s*\)?", "", plan, flags=re.IGNORECASE).rstrip(" ,()")
    return cleaned or None


def _load_cache(provider: str) -> QuotaResult | None:
    cached = _MEMORY_CACHE.get(provider)
    if not cached and CACHE_FILE.exists():
        try:
            full_cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(full_cache, dict) and provider in full_cache:
                cached = full_cache[provider]
                _MEMORY_CACHE[provider] = cached
        except (OSError, json.JSONDecodeError):
            pass

    if isinstance(cached, dict):
        windows = [
            QuotaWindow(
                label=w.get("label", ""),
                used_percent=float(w.get("used_percent", 0.0)),
                used=_number(w.get("used")),
                total=_number(w.get("total")),
                unit=str(w.get("unit", "")),
                resets_at=w.get("resets_at"),
            )
            for w in cached.get("windows", [])
            if isinstance(w, dict)
        ]
        if windows:
            return QuotaResult(
                provider=cached.get("provider", provider.title()),
                windows=windows,
                error=None,
                plan=_clean_plan(cached.get("plan")),
            )
    return None


def _get_cached_time(provider: str) -> float:
    cached = _MEMORY_CACHE.get(provider)
    if not cached and CACHE_FILE.exists():
        try:
            full_cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(full_cache, dict) and provider in full_cache:
                cached = full_cache[provider]
                _MEMORY_CACHE[provider] = cached
        except (OSError, json.JSONDecodeError):
            pass
    if isinstance(cached, dict):
        return float(cached.get("cached_at", 0.0))
    return 0.0


def _save_cache(provider: str, result: QuotaResult) -> None:
    if not result.windows or result.error:
        return
    data = {
        "provider": result.provider,
        "plan": _clean_plan(result.plan),
        "windows": [
            {
                "label": w.label,
                "used_percent": w.used_percent,
                "used": w.used,
                "total": w.total,
                "unit": w.unit,
                "resets_at": w.resets_at,
            }
            for w in result.windows
        ],
        "cached_at": time.time(),
    }
    _MEMORY_CACHE[provider] = data
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        full_cache = {}
        if CACHE_FILE.exists():
            try:
                full_cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if not isinstance(full_cache, dict):
                    full_cache = {}
            except (OSError, json.JSONDecodeError):
                full_cache = {}
        full_cache[provider] = data
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=CACHE_DIR, delete=False
        ) as temp:
            json.dump(full_cache, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
            temp_path = Path(temp.name)
        temp_path.chmod(0o600)
        temp_path.replace(CACHE_FILE)
    except OSError:
        pass



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
    try:
        payload = response.json()
    except ValueError as exc:
        content_type = response.headers.get("Content-Type", "unknown")
        raise ValueError(
            f"API returned invalid JSON from {response.url} "
            f"(HTTP {response.status_code}, Content-Type: {content_type})"
        ) from exc
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


def _github_token() -> str | None:
    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", "github.com"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    token = result.stdout.strip()
    return token if result.returncode == 0 and token else None


def fetch_copilot(settings: dict) -> QuotaResult:
    token = _github_token()
    if not token:
        return QuotaResult(
            "Copilot", error="connect GitHub from the settings menu (`gh auth login --web`)"
        )
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

    now = time.time()
    cooldown = _COOLDOWNS.get("claude", 0.0)
    cached = _load_cache("claude")
    cached_at = _get_cached_time("claude")
    ttl = (
        _number(settings["cache_ttl"])
        if "cache_ttl" in settings and _number(settings["cache_ttl"]) is not None
        else CACHE_TTL
    )

    if cached and (now < cooldown or (now - cached_at < ttl)):
        plan = (
            f"{cached.plan}, cached"
            if cached.plan and "cached" not in str(cached.plan)
            else (cached.plan or "cached")
        )
        return QuotaResult(cached.provider, cached.windows, None, plan)

    try:
        data = _request_json(
            "GET",
            settings.get("url", "https://api.anthropic.com/api/oauth/usage"),
            token,
            {"anthropic-beta": "oauth-2025-04-20"},
        )
    except requests.HTTPError as exc:
        is_429 = (exc.response is not None and exc.response.status_code == 429) or "429" in str(exc)
        if is_429:
            _COOLDOWNS["claude"] = now + COOLDOWN_SECONDS
            if cached:
                plan = (
                    f"{cached.plan}, cached"
                    if cached.plan and "cached" not in str(cached.plan)
                    else (cached.plan or "cached")
                )
                return QuotaResult(cached.provider, cached.windows, None, plan)
            return QuotaResult("Claude", error="rate limited (HTTP 429; retry in 5 minutes)")
        raise
    except requests.RequestException as exc:
        if "429" in str(exc) or "rate" in str(exc).lower():
            _COOLDOWNS["claude"] = now + COOLDOWN_SECONDS
            if cached:
                plan = (
                    f"{cached.plan}, cached"
                    if cached.plan and "cached" not in str(cached.plan)
                    else (cached.plan or "cached")
                )
                return QuotaResult(cached.provider, cached.windows, None, plan)
            return QuotaResult("Claude", error="rate limited (HTTP 429; retry in 5 minutes)")
        raise

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
            identity = next(
                (
                    str(value[key])
                    for key in ("model", "scope", "label", "name")
                    if value.get(key)
                ),
                None,
            )
            if identity and kind in ("weekly_model", "weekly_scoped"):
                label = f"7d {identity}"
            percent = _number(value.get("percent"))
            if label in labels or not percent:
                continue
            window = _window(label, percent=value.get("percent"), reset=value.get("resets_at"))
            if window:
                windows.append(window)
                labels.add(label)
    plan = oauth.get("subscriptionType")
    result = QuotaResult(
        "Claude",
        windows,
        None if windows else "unknown usage format",
        str(plan) if plan else None,
    )
    if windows:
        _save_cache("claude", result)
    return result


def fetch_nanogpt(settings: dict) -> QuotaResult:
    token = _secret(settings, "NANOGPT_API_KEY")
    if not token:
        return QuotaResult("NanoGPT", error="set NANOGPT_API_KEY")
    data = _request_json(
        "GET",
        "https://nano-gpt.com/api/subscription/v1/usage",
        token,
        headers={"x-api-key": token},
    )
    windows = []
    legacy_windows = (
        ("dailyInputTokens", "daily", "tokens"),
        ("weeklyInputTokens", "weekly", "tokens"),
        ("dailyImages", "daily images", "images"),
    )
    current_windows = (
        ("daily", "daily", ""),
        ("monthly", "monthly", ""),
    )
    limits = data.get("limits") if isinstance(data.get("limits"), dict) else {}
    for key, label, unit in legacy_windows + current_windows:
        value = data.get(key)
        if not isinstance(value, dict):
            continue
        percent = _number(value.get("percentUsed"))
        if percent is not None and percent <= 1:
            percent *= 100
        window = _window(
            label,
            used=value.get("used"),
            total=value.get("limit", limits.get(key)),
            percent=percent,
            remaining=value.get("remaining"),
            unit=unit,
            reset=value.get("resetAt")
            or (
                (data.get("period") or {}).get("currentPeriodEnd")
                if key == "monthly" and isinstance(data.get("period"), dict)
                else None
            ),
        )
        if window:
            windows.append(window)
    return QuotaResult("NanoGPT", windows, None if windows else "subscription is inactive or unavailable")


def fetch_ollama(settings: dict) -> QuotaResult:
    token = _secret(settings, "OLLAMA_API_KEY")
    cookie = settings.get("session_cookie") or os.environ.get("OLLAMA_SESSION_COOKIE")
    api_windows = []
    api_plan = None
    if token:
        try:
            data = _request_json("GET", OLLAMA_USAGE_URL, token)
            api_windows = _ollama_usage_windows(data)
            api_plan = _plan_name(data)
            try:
                account = _request_json("POST", OLLAMA_ACCOUNT_URL, token)
                api_plan = _plan_name(account) or api_plan
            except requests.RequestException:
                pass
        except requests.RequestException:
            if not cookie:
                raise
    if cookie:
        try:
            windows, plan, error = _fetch_ollama_settings(str(cookie))
        except requests.RequestException:
            if api_windows:
                return QuotaResult("Ollama", api_windows, plan=api_plan)
            raise
        if windows:
            merged = {window.label: window for window in api_windows}
            merged.update({window.label: window for window in windows})
            ordered = [
                merged.pop(label)
                for label in ("5h", "weekly", "monthly")
                if label in merged
            ]
            ordered.extend(merged.values())
            return QuotaResult("Ollama", ordered, plan=plan or api_plan)
        if not api_windows:
            return QuotaResult("Ollama", error=error)
    if api_windows:
        return QuotaResult("Ollama", api_windows, plan=api_plan)
    if token:
        return QuotaResult("Ollama", error="usage API returned no recognized quotas")
    return QuotaResult(
        "Ollama",
        error="set OLLAMA_API_KEY or OLLAMA_SESSION_COOKIE",
    )


def _fetch_ollama_settings(
    cookie: str,
) -> tuple[list[QuotaWindow], str | None, str]:
    response = requests.get(
        OLLAMA_SETTINGS_URL,
        headers={
            "Accept": "text/html",
            "Cookie": cookie,
            "User-Agent": "howmuch-left/1",
        },
        timeout=TIMEOUT,
        allow_redirects=False,
    )
    response.raise_for_status()
    if response.is_redirect:
        return [], None, "Ollama session cookie expired"
    windows, plan = _parse_ollama_settings(response.text)
    return windows, plan, "settings page returned no recognized quotas"


def _ollama_usage_windows(data: dict) -> list[QuotaWindow]:
    limits = data.get("limits")
    if not isinstance(limits, dict):
        return []
    windows = []
    for name, label in (
        ("session", "5h"),
        ("weekly", "weekly"),
        ("monthly", "monthly"),
    ):
        value = limits.get(name)
        if not isinstance(value, dict):
            continue
        usage = _number(value.get("usage"))
        if usage is not None and 0 <= usage <= 1:
            usage *= 100
        window = _window(
            label,
            percent=usage,
            reset=value.get("resets_at", value.get("reset_at")),
        )
        if window:
            windows.append(window)
    return windows


def _parse_ollama_settings(document: str) -> tuple[list[QuotaWindow], str | None]:
    text = html.unescape(document)
    windows = []
    labels = (
        ("5h", ("5-hour", "5h", "Session", "Hourly")),
        ("weekly", ("Weekly",)),
        ("monthly", ("Monthly",)),
    )
    all_names = tuple(name for _, names in labels for name in names)
    for label, names in labels:
        block = None
        for name in names:
            start = re.search(
                rf'(?:aria-label=["\'])?{re.escape(name)}\s+usage',
                text,
                re.IGNORECASE,
            )
            if start:
                tail = text[start.start() :]
                next_label = re.search(
                    "|".join(
                        rf"{re.escape(other)}\s+usage"
                        for other in all_names
                        if other != name
                    ),
                    tail[len(start.group(0)) :],
                    re.IGNORECASE,
                )
                end = (
                    len(start.group(0)) + next_label.start()
                    if next_label
                    else 10_000
                )
                block = tail[:end]
                break
        if not block:
            continue
        percent_match = re.search(r"([\d.]+)\s*%\s*used", block, re.IGNORECASE)
        if not percent_match:
            percent_match = re.search(
                r"usage\s+([\d.]+)\s*%", block, re.IGNORECASE
            )
        if not percent_match:
            percent_match = re.search(r"width:\s*([\d.]+)%", block, re.IGNORECASE)
        used = total = None
        if label == "monthly":
            amounts = re.search(
                r"\$([\d,.]+)\s+of\s+\$([\d,.]+)(?:\s+used)?",
                block,
                re.IGNORECASE,
            )
            if amounts:
                used = amounts.group(1).replace(",", "")
                total = amounts.group(2).replace(",", "")
        reset_match = re.search(
            r'data-time=["\']([^"\']+)', block, re.IGNORECASE
        )
        window = _window(
            label,
            used=used,
            total=total,
            percent=percent_match.group(1) if percent_match else None,
            unit="USD" if used is not None else "",
            reset=reset_match.group(1) if reset_match else None,
        )
        if window:
            windows.append(window)
    plan_match = re.search(
        r"(?:Cloud|Included)\s+Usage[\s\S]{0,300}?\b(Free|Pro|Max|Business)\b",
        text,
        re.IGNORECASE,
    )
    plan = plan_match.group(1).title() if plan_match else None
    return windows, plan


def fetch_antigravity(_settings: dict) -> QuotaResult:
    try:
        result = subprocess.run(
            ["agy", "--prompt", "/usage"],
            check=False,
            capture_output=True,
            text=True,
            timeout=AGY_TIMEOUT,
        )
    except FileNotFoundError:
        return QuotaResult("Antigravity", error="agy CLI not found on PATH")
    except subprocess.TimeoutExpired:
        return QuotaResult("Antigravity", error="agy --prompt /usage timed out")
    if result.returncode != 0:
        return QuotaResult(
            "Antigravity",
            error=f"agy exited with status {result.returncode}; check CLI login",
        )

    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    row_pattern = re.compile(
        r"^\s*(?P<group>.+?)\s+"
        r"(?P<window>Weekly|Five Hour) Limit Remaining\s+"
        r"(?P<remaining>\d+(?:\.\d+)?)%\s+(?P<reset>\S+)\s*$",
        re.IGNORECASE,
    )
    windows = []
    for line in output.splitlines():
        match = row_pattern.match(line)
        if not match:
            continue
        remaining = _number(match.group("remaining"))
        if remaining is None:
            continue
        window = "weekly" if match.group("window").lower() == "weekly" else "5h"
        windows.append(
            QuotaWindow(
                label=f"{match.group('group').strip()} {window}",
                used_percent=max(0.0, min(100.0, 100.0 - remaining)),
                resets_at=match.group("reset"),
            )
        )
    if not windows:
        return QuotaResult(
            "Antigravity", error="unrecognized output from agy /usage"
        )
    return QuotaResult("Antigravity", windows)


def _plan_name(data: dict) -> str | None:
    plan = (
        data.get("plan")
        or data.get("Plan")
        or data.get("tier")
        or data.get("current_plan")
    )
    subscription = data.get("subscription")
    if not plan and isinstance(subscription, dict):
        plan = subscription.get("plan") or subscription.get("tier") or subscription.get("name")
    if isinstance(plan, dict):
        plan = plan.get("name") or plan.get("id") or plan.get("slug")
    return str(plan) if plan else None


def fetch_devpass(settings: dict) -> QuotaResult:
    token = _secret(settings, "DEVPASS_API_KEY")
    if token:
        payload = _request_json(
            "GET", "https://api.llmgateway.io/v1/key", token
        )
    else:
        return QuotaResult(
            "DevPass",
            error=(
                "set DEVPASS_API_KEY "
                "(dashboard session cookies are not supported)"
            ),
        )
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    windows = []
    for label, used_key, limit_key, reset_key in (
        (
            "monthly",
            "devPlanCreditsUsed",
            "devPlanCreditsLimit",
            "devPlanExpiresAt",
        ),
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
    plan = data.get("devPlan")
    return QuotaResult(
        "DevPass",
        windows,
        None if windows else "unknown usage format",
        str(plan) if plan and plan != "none" else None,
    )


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
        result = fetcher(settings)
        if result.windows and not result.error:
            _save_cache(name, result)
        return result
    except requests.HTTPError as exc:
        is_429 = (exc.response is not None and exc.response.status_code == 429) or "429" in str(exc)
        if is_429:
            _COOLDOWNS[name] = time.time() + COOLDOWN_SECONDS
            cached = _load_cache(name)
            if cached:
                plan = f"{cached.plan}, cached" if cached.plan and "cached" not in str(cached.plan) else (cached.plan or "cached")
                return QuotaResult(cached.provider, cached.windows, None, plan)
            return QuotaResult(name.title(), error="rate limited (HTTP 429; retry in 5 minutes)")
        return QuotaResult(name.title(), error=f"request failed: {exc}")
    except requests.RequestException as exc:
        if "429" in str(exc) or "rate" in str(exc).lower():
            _COOLDOWNS[name] = time.time() + COOLDOWN_SECONDS
            cached = _load_cache(name)
            if cached:
                plan = f"{cached.plan}, cached" if cached.plan and "cached" not in str(cached.plan) else (cached.plan or "cached")
                return QuotaResult(cached.provider, cached.windows, None, plan)
            return QuotaResult(name.title(), error="rate limited (HTTP 429; retry in 5 minutes)")
        return QuotaResult(name.title(), error=f"request failed: {exc}")
    except (TypeError, ValueError, KeyError) as exc:
        return QuotaResult(name.title(), error=f"invalid response: {exc}")
