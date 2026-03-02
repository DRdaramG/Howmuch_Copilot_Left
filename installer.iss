; Inno Setup 6 script for CopilotLeft
; Download Inno Setup from https://jrsoftware.org/isdl.php
;
; After building the executable with PyInstaller (pyinstaller build.spec),
; compile this script with ISCC.exe to produce the installer:
;
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; The resulting setup file will be in the Output\ directory.

#define MyAppName      "CopilotLeft"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "DRdaramG"
#define MyAppURL       "https://github.com/DRdaramG/Howmuch_Copilot_Left"
#define MyAppExeName   "CopilotLeft.exe"
#define MyDistDir      "dist\CopilotLeft"

[Setup]
AppId={{E3A7B6C2-1F4D-4A9E-8B3C-7D2E5F0A1234}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=CopilotLeft-Setup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; Require Windows 10 or later (Windows 11 is also supported)
MinVersion=10.0
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupentry"; Description: "Start CopilotLeft automatically when Windows starts"; GroupDescription: "Windows Startup:"; Flags: unchecked

[Files]
; Include everything PyInstaller collected
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Optional startup entry (only created when the user ticks the task above)
Root: HKCU; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startupentry

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove the registry startup entry on uninstall (if it was set by the app itself)
Filename: "reg.exe"; Parameters: "delete ""HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"" /v ""{#MyAppName}"" /f"; Flags: runhidden; StatusMsg: "Removing startup entry..."
