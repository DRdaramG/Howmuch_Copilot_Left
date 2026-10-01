# Howmuch AI Left

Linux 터미널에서 AI 서비스별 할당량을 1분마다 갱신하는 CLI입니다.

```text
Copilot AI credits       ■■■■□□□□□□ (40%)  600/1500 credits
Codex weekly             ■■□□□□□□□□ (20%)
Claude 5h                ■■■■■□□□□□ (50%)
```

## 지원 서비스

- GitHub Copilot AI credits
- OpenAI Codex의 세션/주간 한도
- Claude Code의 5시간/7일 한도
- NanoGPT의 일간/주간 토큰 및 이미지 한도
- Ollama 로컬 서버 상태(로컬 실행은 할당량 없음)
- LLM Gateway DevPass의 일반/프리미엄 credits

서비스 API가 할당량을 제공하지 않거나 인증되지 않은 경우에도 다른 서비스는 계속
표시됩니다. Copilot, Codex, Claude의 일부 사용량 API는 각 공식 CLI가 사용하는
내부 엔드포인트이므로 공급자가 응답 형식을 변경할 수 있습니다.

## 설치 및 실행

Python 3.10 이상이 필요합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

기본 실행은 60초마다 화면을 갱신합니다. 한 번만 출력하거나 JSON으로 출력할 수도
있습니다.

```bash
python main.py --once
python main.py --json
python main.py --interval 120
python main.py --no-clear
```

`Ctrl+C`로 종료합니다.

## 인증

토큰은 설정 파일보다 환경 변수를 사용하는 것을 권장합니다.

| 서비스 | 인증 방법 |
|---|---|
| Copilot | `COPILOT_TOKEN` (또는 `GITHUB_TOKEN`) |
| Codex | `codex login`으로 생성한 `~/.codex/auth.json`, 또는 `CODEX_ACCESS_TOKEN` |
| Claude | Claude Code의 `~/.claude/.credentials.json`, 또는 `CLAUDE_ACCESS_TOKEN` |
| NanoGPT | `NANOGPT_API_KEY` |
| Ollama | 인증 없음, 기본 주소 `http://localhost:11434` |
| DevPass | `DEVPASS_API_KEY` |

예:

```bash
export COPILOT_TOKEN='...'
export NANOGPT_API_KEY='...'
export DEVPASS_API_KEY='...'
python main.py
```

## 설정

설정 파일은 XDG 표준 경로인
`${XDG_CONFIG_HOME:-~/.config}/howmuch-left/config.json`을 사용합니다. 파일이
없으면 기본값으로 실행합니다.

```json
{
  "refresh_interval_seconds": 60,
  "providers": {
    "copilot": {"enabled": true},
    "codex": {"enabled": true},
    "claude": {"enabled": true},
    "nanogpt": {"enabled": false},
    "ollama": {
      "enabled": true,
      "url": "http://localhost:11434"
    },
    "devpass": {"enabled": false}
  }
}
```

필요한 공급자만 `enabled`로 설정할 수 있으며, 사설 프록시를 쓰는 경우 각 공급자에
`url`을 지정할 수 있습니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 라이선스

MIT
