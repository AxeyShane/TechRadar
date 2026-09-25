; Inno Setup script for TechRadar.
; Ported from Prospector's installer\prospector.iss -- same reasoning
; applies unchanged (see the comments kept below). Targets Inno Setup 6.2.x
; on purpose, same version ceiling as Prospector's.
;
; Compiled by installer\build_installer.ps1, which passes MyAppVersion in.
; To compile by hand:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\techradar.iss

#define MyAppName "TechRadar"
#define MyAppPublisher "Akshay Kharvi"
#define MyAppURL "https://github.com/AxeyShane/TechRadar"
#define MyAppExeName "TechRadar.exe"

; Overridden by the build script: /DMyAppVersion=0.1.0
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

; Where PyInstaller left the one-folder build.
#ifndef MySourceDir
  #define MySourceDir "..\dist\TechRadar"
#endif

[Setup]
; NOTE: The value of AppId uniquely identifies this application. Do not use
; the same AppId value in installers for other applications -- this one is
; freshly generated, not copied from Prospector's.
AppId={{9A293249-B626-40A7-A246-06F387084038}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install: no administrator prompt, no admin account needed. The
; whole point is that a non-technical person can install this on their own.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\dist
OutputBaseFilename=TechRadarSetup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
AppMutex=TechRadarSetupMutex

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\*.pyd"
Type: files; Name: "{app}\python*.dll"
Type: files; Name: "{app}\base_library.zip"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The user's scored items, notes and watch history live under
; %USERPROFILE%\.techradar. That folder is deliberately NOT removed here.
; The Playwright browser cache crawl4ai depends on is large and
; re-fetchable, same reasoning as JobPilot's installer.
Type: filesandordirs; Name: "{localappdata}\ms-playwright"

[Code]
function InitializeSetup(): Boolean;
var
  Version: TWindowsVersion;
begin
  GetWindowsVersionEx(Version);
  if Version.Major < 10 then
  begin
    MsgBox('TechRadar needs Windows 10 or later.', mbCriticalError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;
