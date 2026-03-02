# Howmuch Copilot Left

Windows 시스템 트레이 위젯으로 GitHub Copilot 프리미엄 요청 할당량을 5분마다 자동으로 표시합니다.

> 표시 예시: `172 / 1500`

---

## 기능

| 기능 | 설명 |
|------|------|
| 자동 갱신 | 5분마다 Copilot 할당량을 자동으로 조회하여 트레이 아이콘에 표시 |
| 색상 변화 아이콘 | 잔여 할당량에 따라 아이콘 색상이 초록(여유) → 노랑(보통) → 빨강(부족)으로 변화 |
| 데스크톱 오버레이 | 바탕화면 배경(아이콘 뒤)에 할당량을 보여주는 위젯 표시 (Rainmeter 방식의 WorkerW 레이어) |
| GitHub 로그인 | GitHub Device Flow OAuth를 통한 간편 인증 (VS Code Copilot 확장과 동일한 방식) |
| 수동 토큰 입력 | `gho_`로 시작하는 GitHub OAuth 토큰을 직접 입력하는 대체 인증 방식 |
| 시작 프로그램 등록 | 우클릭 메뉴에서 Windows 로그인 시 자동 실행 설정/해제 |
| 즉시 새로고침 | 우클릭 메뉴에서 즉시 할당량 갱신 가능 |
| 설치 프로그램 | Inno Setup 기반 Windows 설치 프로그램 제공 |

---

## 스크린샷

트레이 아이콘에 **사용량/총량** 형식으로 표시됩니다.

```
[시스템 트레이] ... ●  → 툴팁: "172/1500"
```

바탕화면 우측 하단에 오버레이 위젯이 표시됩니다.

```
┌──────────────┐
│  ⚡ Copilot   │
│   172 / 1500  │
└──────────────┘
```

---

## 시작하기

### 1. 설치 프로그램으로 설치 (권장)

빌드된 설치 프로그램이 릴리스 페이지에 있는 경우 다운로드하여 실행하세요.

```
CopilotLeft-Setup-1.0.0.exe
```

### 2. Python으로 직접 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 실행
python main.py
```

또는 `runthis.bat`을 실행하면 의존성 설치와 앱 실행이 자동으로 진행됩니다.

### 3. GitHub 인증

앱 실행 후 트레이 아이콘을 **우클릭**하여 인증합니다.

- **Login with GitHub**: 브라우저가 열리고 GitHub Device Flow를 통해 인증합니다. 표시되는 코드를 GitHub 페이지에 입력하면 자동으로 토큰이 저장됩니다.
- **Enter Token Manually**: `gho_`로 시작하는 GitHub OAuth 토큰을 직접 입력합니다.

---

## 우클릭 메뉴

| 메뉴 항목 | 설명 |
|-----------|------|
| Refresh Now | 즉시 할당량을 다시 조회 |
| Login with GitHub | GitHub Device Flow OAuth 인증 |
| Enter Token Manually | 토큰 직접 입력 |
| Start with Windows | Windows 시작 시 자동 실행 (레지스트리 등록) |
| Quit | 앱 종료 |

---

## 빌드

### 실행 파일 생성 (PyInstaller)

```bash
pip install pyinstaller
pyinstaller build.spec
# 결과물: dist/CopilotLeft/CopilotLeft.exe
```

### 설치 프로그램 생성 (Inno Setup 6)

1. [Inno Setup 6](https://jrsoftware.org/isdl.php)를 설치합니다.
2. PyInstaller로 실행 파일을 먼저 생성합니다.
3. 아래 명령을 실행합니다:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
# 결과물: Output\CopilotLeft-Setup-1.0.0.exe
```

---

## 파일 구조

```
├── main.py          # 메인 애플리케이션 (시스템 트레이 UI + 데스크톱 오버레이)
├── api.py           # GitHub Copilot 할당량 API 조회 및 Device Flow 인증
├── config.py        # 설정 파일 관리 (%APPDATA%\CopilotLeft\config.json)
├── requirements.txt # Python 의존성
├── build.spec       # PyInstaller 빌드 설정
├── installer.iss    # Inno Setup 6 설치 프로그램 스크립트
├── runthis.bat      # 간편 실행 배치 파일 (의존성 설치 + 실행)
└── README.md        # 프로젝트 설명 문서
```

---

## 설정 파일

설정은 아래 경로에 JSON 형식으로 저장됩니다:

```
%APPDATA%\CopilotLeft\config.json
```

저장되는 설정 항목:

| 항목 | 타입 | 설명 |
|------|------|------|
| `api_key` | string | GitHub OAuth 토큰 |
| `auto_start` | boolean | Windows 시작 시 자동 실행 여부 |

---

## 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `pystray` | 0.19.5 | Windows 시스템 트레이 아이콘 |
| `Pillow` | 12.1.1 | 트레이 아이콘 이미지 생성 |
| `requests` | 2.32.3 | GitHub API HTTPS 요청 |

---

## 할당량 초기화 시점

매월 1일 UTC 00:00 (한국 시간 오전 9시)에 Copilot 프리미엄 요청 할당량이 초기화됩니다.

---

## API 동작 방식

이 앱은 GitHub 내부 API 엔드포인트를 사용하여 할당량을 조회합니다:

```
GET https://api.github.com/copilot_internal/user
```

응답의 `quota_snapshots.premium_interactions` 필드에서 `entitlement`(총 할당량)과 `quota_remaining`(잔여량)을 읽어 사용량을 계산합니다.

인증에는 GitHub Copilot VS Code 확장과 동일한 OAuth Client ID (`Iv1.b507a08c87ecfe98`)를 사용하는 Device Flow 방식을 지원합니다.

---

## 라이선스

MIT
