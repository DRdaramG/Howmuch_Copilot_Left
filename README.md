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

초기화 시각은 시스템 로컬 시간대의 24시간 형식으로 표시합니다. Claude의 중복 한도와
사용하지 않는 0% 세부 한도는 생략합니다. OpenAI 응답이 별도 한도를 제공하면 Codex,
ChatGPT(Chatpass), 코드 리뷰 한도를 각각 표시합니다.

## 설치 및 실행

Python 3.10 이상이 필요합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

기본 실행은 60초마다 화면을 갱신합니다. 한 번만 출력하거나 JSON으로 출력할 수도
있습니다. 대화형 실행은 별도 화면에 현재 상태만 표시하며, 서비스별 테마 색상을
적용합니다. 색상을 끄려면 `NO_COLOR=1` 환경 변수를 사용합니다.

```bash
python main.py --once
python main.py --json
python main.py --interval 120
python main.py --no-clear
```

`Ctrl+C`로 종료합니다. 갱신을 기다리는 동안 `Ctrl+S`를 누르면 대화형 설정 메뉴가
열립니다. 메뉴에서 GitHub/Codex/Claude 웹 인증, API 키 등록, 서비스 활성화, 갱신
주기 변경을 할 수 있으며 인증이나 키 등록에 성공한 서비스는 자동으로 활성화됩니다.

## 인증

토큰은 설정 파일보다 환경 변수를 사용하는 것을 권장합니다.

| 서비스 | 인증 방법 |
|---|---|
| Copilot | `gh auth login --web`으로 GitHub 웹 인증 |
| Codex | `codex login`으로 생성한 `~/.codex/auth.json`, 또는 `CODEX_ACCESS_TOKEN` |
| Claude | Claude Code의 `~/.claude/.credentials.json`, 또는 `CLAUDE_ACCESS_TOKEN` |
| NanoGPT | `NANOGPT_API_KEY` |
| Ollama Cloud | `OLLAMA_API_KEY`, 또는 `OLLAMA_SESSION_COOKIE` |
| Antigravity | `ANTIGRAVITY_ACCESS_TOKEN` |
| DevPass | `DEVPASS_API_KEY`, 또는 `DEVPASS_SESSION_COOKIE` |

예:

```bash
gh auth login --web
export NANOGPT_API_KEY='...'
export OLLAMA_API_KEY='...'
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
    "ollama": {"enabled": false},
    "antigravity": {"enabled": false, "url": "https://..."},
    "devpass": {"enabled": false}
  }
}
```

필요한 공급자만 `enabled`로 설정할 수 있으며, 사설 프록시를 쓰는 경우 각 공급자에
`url`을 지정할 수 있습니다.

Ollama Cloud는 API 키로 고정된 `https://ollama.com/api/usage`를 조회해 세션·주간·
월간 사용량을 표시합니다. API 키는 `Ctrl+S` 설정 메뉴에서 등록할 수도 있습니다.
API 키를 사용할 수 없으면 브라우저 개발자 도구에서 `ollama.com`의 전체
`__Secure-session=...` 쿠키 값을 복사해 `OLLAMA_SESSION_COOKIE`로 지정할 수
있습니다. 이 경우 로그인된 설정 페이지의 서버 렌더링 HTML을 읽으므로 별도 headless
브라우저 설치가 필요하지 않습니다. 쿠키는 비밀번호처럼 취급하고 환경 변수로만
전달하는 것을 권장합니다.

Antigravity는 계정에 제공된 할당량 API 또는 호환 프록시 주소를
`ANTIGRAVITY_USAGE_URL`(또는 설정의 `url`)로 지정해야 합니다. 응답의 요금제와
5시간·일간·주간·월간 한도 및 초기화 시각을 인식해 표시합니다.

DevPass는 API 키로 공식 `GET /v1/key` 사용량 API를 조회합니다. 또는
`https://devpass.llmgateway.io/dashboard/usage`에 로그인한 브라우저의
`better-auth.session_token` 쿠키 전체 값을 `DEVPASS_SESSION_COOKIE`로 지정하면
대시보드가 사용하는 상태 API에서 월간 및 프리미엄 주간 사용량을 읽습니다. 세션
쿠키는 비밀번호처럼 취급하고 환경 변수로만 전달하는 것을 권장합니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

## 라이선스

MIT
