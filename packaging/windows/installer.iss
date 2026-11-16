#define AppName "Syllabus Auditor"
#define AppVersion "1.1.0"
#define AppExe "SyllabusAuditor.exe"

[Setup]
AppId={{F361D794-03B6-4F67-A31A-25B4C388D190}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Syllabus Auditor
DefaultDirName={localappdata}\Programs\Syllabus Auditor
DefaultGroupName=Syllabus Auditor
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=SyllabusAuditor_Setup_1.0.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=syllabus-auditor.ico
CloseApplications=yes

[Files]
Source: "..\..\dist\SyllabusAuditor\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Syllabus Auditor"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\Syllabus Auditor"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Syllabus Auditor"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Intentionally no user-data cleanup: data persists in
; %LOCALAPPDATA%\SyllabusAuditor\data after uninstall or upgrades.
