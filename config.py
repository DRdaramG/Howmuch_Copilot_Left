"""Configuration management for CopilotLeft."""

import json
import os

APP_NAME = "CopilotLeft"
CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME
)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

_DEFAULTS = {
    "api_key": "",
    "auto_start": False,
}


def load() -> dict:
    """Load configuration from disk, returning defaults for missing keys."""
    cfg = dict(_DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items() if k in _DEFAULTS})
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict) -> None:
    """Persist configuration to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
