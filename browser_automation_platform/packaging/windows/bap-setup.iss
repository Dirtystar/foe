; Inno Setup script for the Browser Automation Platform beta installer.
; Wraps the PyInstaller one-folder output (dist\BAP) into a single .exe
; installer with a Start Menu shortcut and a clean uninstaller.
;
; Build (on Windows, after `pyinstaller packaging\windows\bap.spec`):
;   ISCC.exe packaging\windows\bap-setup.iss
; Output: packaging\windows\Output\BAP-Setup-0.1.0.exe

#define AppName "Browser Automation Platform"
#define AppShortName "BAP"
#define AppVersion "0.1.0"
#define AppPublisher "BAP"
#define AppExeName "BAP.exe"

[Setup]
; A stable GUID identifies the app across upgrades — do not change it.
AppId={{9F1D5B4E-6C2A-4B7E-9E1F-BA0100A0BE7A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
; Per-user install: no administrator rights required (beta-friendly).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppShortName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=BAP-Setup-{#AppVersion}
SetupIconFile=assets\bap.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The entire PyInstaller onedir output.
Source: "..\..\dist\BAP\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; First-run Chromium installer helper (for real automation).
Source: "install-browser.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName} (CLI)"; Filename: "{cmd}"; Parameters: "/K ""{app}\bap.exe"" --help"; Comment: "Open a console with the BAP CLI"
Name: "{group}\Install Browser (for real automation)"; Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -File ""{app}\install-browser.ps1"""; Comment: "Download Chromium for --real runs"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Description: "Launch {#AppName}"; Filename: "{app}\{#AppExeName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Installed files only. User data under %LOCALAPPDATA%\BAP is handled in [Code].
Type: filesandordirs; Name: "{app}"

[Code]
// On uninstall, offer to also remove the per-user data tree
// (%LOCALAPPDATA%\BAP: config, logs, data, plugins). Kept opt-in so a
// reinstall preserves history and configuration by default.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\BAP');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also remove your BAP data (config, logs, history) at'#13#10
                + DataDir + ' ?', mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
