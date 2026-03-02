"""GitHub Copilot quota API interaction.

Uses the internal Copilot user endpoint to fetch premium-request usage:
    GET https://api.github.com/copilot_internal/user

The response contains ``quota_snapshots.premium_interactions`` with
``used`` and ``limit`` fields.

Token generation uses the GitHub OAuth **Device Flow** with the same
client ID used by the official GitHub Copilot VS Code extension, so the
resulting ``gho_`` token already has the required Copilot scope.

Reference: https://copilotstats.com/
"""

import logging
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 30  # seconds

# GitHub OAuth App client ID used by the Copilot VS Code extension.
# This is a public, non-secret identifier embedded in the extension source.
DEVICE_FLOW_CLIENT_ID = "Iv1.b507a08c87ecfe98"


# ---------------------------------------------------------------------------
# Device Flow token generation
# ---------------------------------------------------------------------------

def request_device_code() -> dict:
    """Start the Device Flow and return the device-code payload.

    Returns a dict with at least ``device_code``, ``user_code``, and
    ``verification_uri``.
    """
    resp = requests.post(
        "https://github.com/login/device/code",
        data={
            "client_id": DEVICE_FLOW_CLIENT_ID,
            "scope": "copilot",
        },
        headers={"Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.debug("Device code response: %s", {k: v for k, v in data.items() if k != "device_code"})
    return data


def poll_for_token(device_code: str, interval: int = 5, timeout: int = 300) -> Optional[str]:
    """Poll GitHub until the user authorises the device, then return the token.

    Returns *None* if the user does not authorise within *timeout* seconds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        resp = requests.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": DEVICE_FLOW_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        data = resp.json()
        if "access_token" in data:
            logger.info("Device Flow: token obtained successfully.")
            return data["access_token"]
        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        # expired_token, access_denied, etc.
        logger.warning("Device Flow error: %s", error)
        return None
    logger.warning("Device Flow timed out after %d seconds.", timeout)
    return None


# ---------------------------------------------------------------------------
# Quota fetch
# ---------------------------------------------------------------------------

def fetch_quota(api_key: str) -> Tuple[Optional[float], Optional[int]]:
    """Return *(used, total)* premium-request counts.

    Calls ``GET /copilot_internal/user`` and reads
    ``quota_snapshots.premium_interactions``.

    Returns *(None, None)* on any error so callers can show a fallback.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(
            f"{_GITHUB_API}/copilot_internal/user",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.HTTPError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            logger.warning("Invalid or expired token (401). Please generate a new token.")
        elif status == 403:
            logger.warning("Access denied (403). Make sure you have an active Copilot subscription.")
        else:
            logger.warning("HTTP error: %s", exc)
        return None, None
    except requests.exceptions.RequestException as exc:
        logger.warning("Network error: %s", exc)
        return None, None
    except ValueError as exc:
        logger.warning("JSON parse error: %s", exc)
        return None, None

    # Check for plan
    if data.get("_noPlan") or not data.get("quota_snapshots"):
        snapshots = data.get("quota_snapshots")
        if not snapshots or not isinstance(snapshots, dict):
            logger.warning(
                "No quota_snapshots in response. Keys: %s",
                list(data.keys()),
            )
            return None, None

    snapshots = data["quota_snapshots"]
    premium = snapshots.get("premium_interactions")
    if not isinstance(premium, dict):
        logger.warning(
            "No premium_interactions in quota_snapshots. Keys: %s",
            list(snapshots.keys()),
        )
        return None, None

    # Response fields:
    #   entitlement    – total monthly limit (e.g. 1500)
    #   quota_remaining – remaining count (e.g. 1310.36)
    #   remaining       – remaining (integer)
    #   percent_remaining – percentage left (e.g. 87.35)
    entitlement = premium.get("entitlement")
    remaining = premium.get("quota_remaining") or premium.get("remaining")

    if entitlement is not None and remaining is not None:
        try:
            total = int(entitlement)
            used_f = round(float(entitlement) - float(remaining), 2)
            logger.info(
                "Copilot usage: %.2f / %d  (remaining: %s)",
                used_f, total, remaining,
            )
            return used_f, total
        except (TypeError, ValueError):
            logger.warning(
                "Cannot parse entitlement=%r / remaining=%r",
                entitlement, remaining,
            )
            return None, None

    # Fallback: try used/limit directly
    used = premium.get("used")
    limit = premium.get("limit")
    if used is not None and limit is not None:
        try:
            return float(used), int(limit)
        except (TypeError, ValueError):
            pass

    logger.warning("Cannot extract quota from premium_interactions: %s", premium)
    return None, None
