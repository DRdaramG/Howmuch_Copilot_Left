"""XDG configuration for the Linux CLI."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
CONFIG_FILE = CONFIG_HOME / "howmuch-left" / "config.json"

DEFAULTS = {
    "refresh_interval_seconds": 60,
    "providers": {
        "copilot": {"enabled": True},
        "codex": {"enabled": True},
        "claude": {"enabled": True},
        "nanogpt": {"enabled": False},
        "ollama": {"enabled": True, "url": "http://localhost:11434"},
        "devpass": {"enabled": False},
    },
}


def load(path: Path | None = None) -> dict:
    settings = copy.deepcopy(DEFAULTS)
    config_path = path or CONFIG_FILE
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return settings
    if not isinstance(data, dict):
        return settings
    if isinstance(data.get("refresh_interval_seconds"), int):
        settings["refresh_interval_seconds"] = data["refresh_interval_seconds"]
    if isinstance(data.get("providers"), dict):
        for name, values in data["providers"].items():
            if isinstance(values, dict):
                settings["providers"].setdefault(name, {}).update(values)
    return settings
