"""XDG configuration for the Linux CLI."""

from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
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
        "ollama": {"enabled": False},
        "antigravity": {"enabled": False},
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


def edit(path: Path | None = None) -> None:
        config_path = path or CONFIG_FILE
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            config_path.write_text(
                json.dumps(DEFAULTS, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            config_path.chmod(0o600)
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        subprocess.run([*shlex.split(editor), str(config_path)], check=False)
    if not isinstance(data, dict):
        return settings
    if isinstance(data.get("refresh_interval_seconds"), int):
        settings["refresh_interval_seconds"] = data["refresh_interval_seconds"]
    if isinstance(data.get("providers"), dict):
        for name, values in data["providers"].items():
            if isinstance(values, dict):
                settings["providers"].setdefault(name, {}).update(values)
    return settings
