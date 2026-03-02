# Howmuch Copilot Left

Windows 11 ?‘ì—… ?œì‹œì¤??¸ë ˆ???„ì ¯?¼ë¡œ GitHub Copilot ? ë‹¹?‰ì„ 5ë¶„ë§ˆ???ë™ ?œì‹œ?©ë‹ˆ??
?? `172.7/1500`

> **A Windows 11 system-tray widget that automatically reads and displays your GitHub Copilot quota every 5 minutes.**  
> Example display: `172.7/1500`

---

## ê¸°ëŠ¥ / Features

| ê¸°ëŠ¥ | ?¤ëª… |
|------|------|
| ?ë™ ê°±ì‹  | 5ë¶„ë§ˆ??Copilot ? ë‹¹?‰ì„ ?ë™?¼ë¡œ ?½ì–´?€ ?¸ë ˆ???„ì´ì½˜ì— ?œì‹œ |
| ê°„í¸ ?¸ì¦ | `gho_` ë¡??œì‘?˜ëŠ” GitHub OAuth ? í° ??ë²ˆë§Œ ?…ë ¥ |
| ?œì‘ ?„ë¡œê·¸ë¨ | ?°í´ë¦?ë©”ë‰´?ì„œ Windows ë¡œê·¸?????ë™ ?¤í–‰ ?¤ì • |
| ì¦‰ì‹œ ?ˆë¡œê³ ì¹¨ | ?°í´ë¦?ë©”ë‰´?ì„œ ì¦‰ì‹œ ? ë‹¹??ê°±ì‹  ê°€??|
| ?¤ì¹˜ ?„ë¡œê·¸ë¨ | 

---

## ?¤í¬ë¦°ìƒ· / Screenshot

?¸ë ˆ???„ì´ì½˜ì— **?„ì¬?¬ìš©/ìµœë?** ?•ì‹?¼ë¡œ ?œì‹œ?©ë‹ˆ??

```
[?œìŠ¤???¸ë ˆ?? ... 172.7/1500  ???´íŒ: "Copilot Left  172.7/1500"
```

---

## ?œì‘?˜ê¸° / Getting Started

### 1. GitHub OAuth ? í° ë°œê¸‰

1. GitHub ??**Settings** ??**Developer settings** ??**Personal access tokens** ??**Tokens (classic)**
2. **Generate new token** ?´ë¦­ ??`copilot` ?¤ì½”??? íƒ
3. ?ì„±??? í°(`gho_...`) ??ë³µì‚¬

?ëŠ” [GitHub Copilot VS Code ?•ì¥](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot)???´ë? ?¤ì¹˜??ê²½ìš°, ?•ì¥??ë³´ê??˜ëŠ” ? í°???¬ìš©?????ˆìŠµ?ˆë‹¤.

### 2. ?¤ì¹˜ ?„ë¡œê·¸ë¨?¼ë¡œ ?¤ì¹˜ (ê¶Œì¥)

> ë¹Œë“œ???¤ì¹˜ ?„ë¡œê·¸ë¨??ë¦´ë¦¬???˜ì´ì§€???ˆëŠ” ê²½ìš° ?¤ìš´ë¡œë“œ?˜ì—¬ ?¤í–‰?˜ì„¸??

```
CopilotLeft-Setup-1.0.0.exe
```

### 3. Python?¼ë¡œ ì§ì ‘ ?¤í–‰

```bash
# ?˜ì¡´???¤ì¹˜
pip install -r requirements.txt

# ?¤í–‰
python main.py
```

?±ì´ ?¤í–‰?˜ë©´ ?¸ë ˆ?´ì— ?„ì´ì½˜ì´ ?œì‹œ?©ë‹ˆ?? **?°í´ë¦???Set API Key** ?ì„œ ? í°???…ë ¥?˜ì„¸??

---

## ë¹Œë“œ / Build

### ?¤í–‰ ?Œì¼ ?ì„± (PyInstaller)

```bash
pip install pyinstaller
pyinstaller build.spec
# ê²°ê³¼ë¬? dist/CopilotLeft/CopilotLeft.exe
```

### ?¤ì¹˜ ?„ë¡œê·¸ë¨ ?ì„± (

1. [
2. PyInstallerë¡??¤í–‰ ?Œì¼ ë¨¼ì? ?ì„±
3. ?„ë˜ ëª…ë ¹ ?¤í–‰:

```bat
"C:\Program Files (x86)\
# ê²°ê³¼ë¬? Output\CopilotLeft-Setup-1.0.0.exe
```

---

## ?Œì¼ êµ¬ì¡° / File Structure

```
?œâ??€ main.py          # ë©”ì¸ ? í”Œë¦¬ì??´ì…˜ (?œìŠ¤???¸ë ˆ??UI)
?œâ??€ api.py           # GitHub Copilot ? ë‹¹??API ì¡°íšŒ
?œâ??€ config.py        # ?¤ì • ?Œì¼ ê´€ë¦?(%APPDATA%\CopilotLeft\config.json)
?œâ??€ requirements.txt # Python ?˜ì¡´??
?œâ??€ build.spec       # PyInstaller ë¹Œë“œ ?¤ì •
?”â??€ installer.iss    # 
```

---

## ?¤ì • ?Œì¼ ?„ì¹˜ / Config Location

```
%APPDATA%\CopilotLeft\config.json
```

---

## ?˜ì¡´??/ Dependencies

| ?¨í‚¤ì§€ | ë²„ì „ | ?©ë„ |
|--------|------|------|
| `pystray` | 0.19.5 | Windows ?œìŠ¤???¸ë ˆ???„ì´ì½?|
| `Pillow` | 10.3.0 | ?¸ë ˆ???„ì´ì½??´ë?ì§€ ?ì„± |
| `requests` | 2.32.3 | HTTPS API ?”ì²­ |

---

## ? ë‹¹??ì´ˆê¸°???œê°„

?œêµ­ ê¸°ì? **ë§¤ì›” 1???¤ì „ 9??* (UTC 00:00) ??Copilot ? ë‹¹?‰ì´ ì´ˆê¸°?”ë©?ˆë‹¤.

---

## ?¼ì´? ìŠ¤ / License

MIT
