"""XDG configuration for the Linux CLI."""

from __future__ import annotations

import copy
import getpass
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

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

OAUTH_COMMANDS = {
    "copilot": ["gh", "auth", "login", "--hostname", "github.com", "--web"],
    "codex": ["codex", "login"],
    "claude": ["claude", "login"],
}

KEY_NAMES = {
    "codex": "CODEX_ACCESS_TOKEN",
    "claude": "CLAUDE_ACCESS_TOKEN",
    "nanogpt": "NANOGPT_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "antigravity": "ANTIGRAVITY_ACCESS_TOKEN",
    "devpass": "DEVPASS_API_KEY",
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


def save(settings: dict, path: Path | None = None) -> None:
    config_path = path or CONFIG_FILE
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=config_path.parent, delete=False
    ) as temporary:
        json.dump(settings, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o600)
    temporary_path.replace(config_path)


def _choose_provider(
    settings: dict,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
    allowed: set[str] | None = None,
) -> str | None:
    providers = [
        name for name in settings["providers"] if allowed is None or name in allowed
    ]
    for index, name in enumerate(providers, 1):
        output_fn(f"  [{index}] {name}")
    choice = input_fn("서비스 번호 (취소: Enter): ").strip()
    if not choice:
        return None
    try:
        index = int(choice)
        if not 1 <= index <= len(providers):
            raise ValueError
        return providers[index - 1]
    except ValueError:
        output_fn("잘못된 번호입니다.")
        return None


def menu(
    path: Path | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    secret_input_fn: Callable[[str], str] = getpass.getpass,
    output_fn: Callable[[str], None] = print,
    run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    settings = load(path)
    while True:
        output_fn("\n설정 메뉴")
        output_fn("  [1] 웹/OAuth 연결")
        output_fn("  [2] API 키 등록")
        output_fn("  [3] 서비스 켜기/끄기")
        output_fn("  [4] 갱신 주기 변경")
        output_fn("  [0] 완료")
        choice = input_fn("선택: ").strip()

        if choice == "0":
            return settings
        if choice == "1":
            provider = _choose_provider(
                settings, input_fn, output_fn, set(OAUTH_COMMANDS)
            )
            if provider:
                try:
                    result = run_fn(OAUTH_COMMANDS[provider], check=False)
                except FileNotFoundError:
                    output_fn(f"{provider} CLI를 찾을 수 없습니다.")
                    continue
                if result.returncode == 0:
                    settings["providers"][provider]["enabled"] = True
                    save(settings, path)
                    output_fn(f"{provider} OAuth 연결을 완료했습니다.")
                else:
                    output_fn(f"{provider} OAuth 연결에 실패했습니다.")
        elif choice == "2":
            provider = _choose_provider(
                settings, input_fn, output_fn, set(KEY_NAMES)
            )
            if provider:
                token = secret_input_fn(f"{KEY_NAMES[provider]}: ").strip()
                if token:
                    settings["providers"][provider]["token"] = token
                    settings["providers"][provider]["enabled"] = True
                    save(settings, path)
                    output_fn(f"{provider} 키를 저장했습니다.")
        elif choice == "3":
            provider = _choose_provider(settings, input_fn, output_fn)
            if provider:
                values = settings["providers"][provider]
                values["enabled"] = not values.get("enabled", False)
                save(settings, path)
                state = "켰습니다" if values["enabled"] else "껐습니다"
                output_fn(f"{provider} 서비스를 {state}.")
        elif choice == "4":
            value = input_fn("갱신 주기(초): ").strip()
            try:
                interval = int(value)
                if interval < 1:
                    raise ValueError
            except ValueError:
                output_fn("1 이상의 정수를 입력하세요.")
            else:
                settings["refresh_interval_seconds"] = interval
                save(settings, path)
                output_fn("갱신 주기를 저장했습니다.")
        else:
            output_fn("메뉴 번호를 선택하세요.")
