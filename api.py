"""GitHub Copilot quota API interaction."""

import base64
import json
import logging
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Endpoint used by the Copilot VS Code extension to obtain a short-lived token.
# The response body includes a `usage` object with `used` and `total` counters
# that reflect the monthly premium-request quota for Copilot Pro subscribers.
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"

REQUEST_TIMEOUT = 30  # seconds

# Identify the client as the VS Code Copilot extension.
# These values mirror the headers sent by the official extension so that
# the GitHub endpoint accepts the request.
_EDITOR_VERSION = "vscode/1.85.0"
_PLUGIN_VERSION = "copilot/1.138.0"
_USER_AGENT = "GitHubCopilotChat/0.11.0"


def _parse_jwt_payload(token: str) -> dict:
    """Decode the payload section of a JWT without verification."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        # JWT uses URL-safe base64 without padding
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(payload_bytes)
    except Exception:  # pylint: disable=broad-except
        return {}


def fetch_quota(api_key: str) -> Tuple[Optional[float], Optional[int]]:
    """Return (used, total) quota counts for the given Copilot OAuth token.

    Returns (None, None) on any error so callers can display a suitable message.

    The ``api_key`` must be a GitHub OAuth token (typically starts with
    ``gho_``) that has the ``copilot`` scope.
    """
    headers = {
        "Authorization": f"token {api_key}",
        "Accept": "application/json",
        # Identify as the VS Code extension so the endpoint accepts the request
        "Editor-Version": _EDITOR_VERSION,
        "Editor-Plugin-Version": _PLUGIN_VERSION,
        "User-Agent": _USER_AGENT,
    }

    try:
        response = requests.get(
            COPILOT_TOKEN_URL, headers=headers, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.HTTPError as exc:
        logger.warning("HTTP error fetching Copilot quota: %s", exc)
        return None, None
    except requests.exceptions.RequestException as exc:
        logger.warning("Network error fetching Copilot quota: %s", exc)
        return None, None
    except ValueError as exc:
        logger.warning("JSON parse error fetching Copilot quota: %s", exc)
        return None, None

    # 1. Prefer an explicit top-level `usage` object in the response body
    usage = data.get("usage")
    if isinstance(usage, dict):
        used = usage.get("used")
        total = usage.get("total")
        if used is not None and total is not None:
            try:
                return float(used), int(total)
            except (TypeError, ValueError):
                pass

    # 2. Fall back to decoding the JWT `token` field if present
    jwt_token = data.get("token", "")
    if jwt_token:
        payload = _parse_jwt_payload(jwt_token)
        used = payload.get("quota_used") or payload.get("used")
        total = payload.get("quota_total") or payload.get("total")
        if used is not None and total is not None:
            try:
                return float(used), int(total)
            except (TypeError, ValueError):
                pass

    logger.warning("Unexpected API response structure: %s", list(data.keys()))
    return None, None
