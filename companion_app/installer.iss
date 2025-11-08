; Inno Setup Script for Luminisbot Companion
; Download Inno Setup from: https://jrsoftware.org/isdl.php

#define MyAppName "Luminisbot Companion"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Luminis Gaming"
#define MyAppURL "https://github.com/Luminis-Gaming/Luminisbot"
#define MyAppExeName "LuminisbotCompanion.exe"

[Setup]
; App identification
AppId={{7F8E9D4C-1A2B-4C5D-8E9F-0A1B2C3D4E5F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation directories
DefaultDirName={autopf}\Luminisbot
DefaultGroupName=Luminisbot
DisableProgramGroupPage=yes

; Output
OutputDir=installer
OutputBaseFilename=LuminisbotCompanion-Setup-v{#MyAppVersion}

; Compression
Compression=lzma
SolidCompression=yes

; Modern UI
WizardStyle=modern

; Icons
SetupIconFile=luminis_logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; Privileges
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Architecture
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startupicon"; Description: "Start automatically with Windows"; GroupDescription: "Startup options:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "luminis_logo.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "luminis_logo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; Startup (if selected)
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\Roaming\.luminisbot_companion.json"

[Code]
function InitializeSetup(): Boolean;
var
  OldUninstallString: String;
  ResultCode: Integer;
begin
  Result := True;
  
  // Check if app is already installed
  if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1', 'UninstallString', OldUninstallString) then
  begin
    if MsgBox('Luminisbot Companion is already installed. Do you want to uninstall the old version first?', mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec(RemoveQuotes(OldUninstallString), '/SILENT', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      Result := True;
    end
    else
    begin
      Result := False;
    end;
  end;
end;

