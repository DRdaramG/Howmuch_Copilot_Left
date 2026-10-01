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
- Ollama Cloud 요금제 및 할당량
- Google Antigravity 요금제 및 할당량
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

`Ctrl+C`로 종료합니다. 갱신을 기다리는 동안 `Ctrl+S`를 누르면 `$VISUAL` 또는
`$EDITOR`로 설정 파일을 열고, 편집이 끝나면 즉시 설정을 다시 읽습니다.

## 인증

토큰은 설정 파일보다 환경 변수를 사용하는 것을 권장합니다.

| 서비스 | 인증 방법 |
|---|---|
| Copilot | `COPILOT_TOKEN` (또는 `GITHUB_TOKEN`) |
| Codex | `codex login`으로 생성한 `~/.codex/auth.json`, 또는 `CODEX_ACCESS_TOKEN` |
| Claude | Claude Code의 `~/.claude/.credentials.json`, 또는 `CLAUDE_ACCESS_TOKEN` |
| NanoGPT | `NANOGPT_API_KEY` |
| Ollama Cloud | `OLLAMA_API_KEY` |
| Antigravity | `ANTIGRAVITY_ACCESS_TOKEN` |
| DevPass | `DEVPASS_API_KEY` |

예:

```bash
export COPILOT_TOKEN='...'
export NANOGPT_API_KEY='...'
export OLLAMA_API_KEY='...'
export OLLAMA_USAGE_URL='https://...'
export ANTIGRAVITY_ACCESS_TOKEN='...'
export ANTIGRAVITY_USAGE_URL='https://...'
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
    "ollama": {"enabled": false, "url": "https://..."},
    "antigravity": {"enabled": false, "url": "https://..."},
    "devpass": {"enabled": false}
  }
}
```

필요한 공급자만 `enabled`로 설정할 수 있으며, 사설 프록시를 쓰는 경우 각 공급자에
`url`을 지정할 수 있습니다.

Ollama Cloud와 Antigravity는 현재 공개 문서에 할당량 조회 API나 외부 OAuth 흐름이
명시되어 있지 않습니다. 따라서 계정에 제공된 할당량 API 또는 호환 프록시 주소를
각각 `OLLAMA_USAGE_URL`, `ANTIGRAVITY_USAGE_URL`(또는 설정의 `url`)로 지정해야
합니다. 응답의 요금제와 5시간·일간·주간·월간 한도 및 초기화 시각을 인식해
표시합니다. 토큰을 설정 파일에 직접 넣을 수도 있지만 환경 변수 사용을 권장합니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 라이선스

MIT
