# Howmuch Copilot Left

Windows 11 작업 표시줄 트레이 위젯으로 GitHub Copilot 할당량을 5분마다 자동 표시합니다.
예: `172.7/1500`

> **A Windows 11 system-tray widget that automatically reads and displays your GitHub Copilot quota every 5 minutes.**  
> Example display: `172.7/1500`

---

## 기능 / Features

| 기능 | 설명 |
|------|------|
| 자동 갱신 | 5분마다 Copilot 할당량을 자동으로 읽어와 트레이 아이콘에 표시 |
| 간편 인증 | `gho_` 로 시작하는 GitHub OAuth 토큰 한 번만 입력 |
| 시작 프로그램 | 우클릭 메뉴에서 Windows 로그인 시 자동 실행 설정 |
| 즉시 새로고침 | 우클릭 메뉴에서 즉시 할당량 갱신 가능 |
| 설치 프로그램 | Inno Setup 기반 Windows 설치 파일 제공 |

---

## 스크린샷 / Screenshot

트레이 아이콘에 **현재사용/최대** 형식으로 표시됩니다.

```
[시스템 트레이] ... 172.7/1500  ← 툴팁: "Copilot Left  172.7/1500"
```

---

## 시작하기 / Getting Started

### 1. GitHub OAuth 토큰 발급

1. GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
2. **Generate new token** 클릭 후 `copilot` 스코프 선택
3. 생성된 토큰(`gho_...`) 을 복사

또는 [GitHub Copilot VS Code 확장](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot)이 이미 설치된 경우, 확장이 보관하는 토큰을 사용할 수 있습니다.

### 2. 설치 프로그램으로 설치 (권장)

> 빌드된 설치 프로그램이 릴리스 페이지에 있는 경우 다운로드하여 실행하세요.

```
CopilotLeft-Setup-1.0.0.exe
```

### 3. Python으로 직접 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 실행
python main.py
```

앱이 실행되면 트레이에 아이콘이 표시됩니다. **우클릭 → Set API Key** 에서 토큰을 입력하세요.

---

## 빌드 / Build

### 실행 파일 생성 (PyInstaller)

```bash
pip install pyinstaller
pyinstaller build.spec
# 결과물: dist/CopilotLeft/CopilotLeft.exe
```

### 설치 프로그램 생성 (Inno Setup)

1. [Inno Setup 6](https://jrsoftware.org/isdl.php) 설치
2. PyInstaller로 실행 파일 먼저 생성
3. 아래 명령 실행:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
# 결과물: Output\CopilotLeft-Setup-1.0.0.exe
```

---

## 파일 구조 / File Structure

```
├── main.py          # 메인 애플리케이션 (시스템 트레이 UI)
├── api.py           # GitHub Copilot 할당량 API 조회
├── config.py        # 설정 파일 관리 (%APPDATA%\CopilotLeft\config.json)
├── requirements.txt # Python 의존성
├── build.spec       # PyInstaller 빌드 설정
└── installer.iss    # Inno Setup 설치 스크립트
```

---

## 설정 파일 위치 / Config Location

```
%APPDATA%\CopilotLeft\config.json
```

---

## 의존성 / Dependencies

| 패키지 | 버전 | 용도 |
|--------|------|------|
| `pystray` | 0.19.5 | Windows 시스템 트레이 아이콘 |
| `Pillow` | 10.3.0 | 트레이 아이콘 이미지 생성 |
| `requests` | 2.32.3 | HTTPS API 요청 |

---

## 할당량 초기화 시간

한국 기준 **매월 1일 오전 9시** (UTC 00:00) 에 Copilot 할당량이 초기화됩니다.

---

## 라이선스 / License

MIT