; Inno Setup script - packs dist\FindIt\ into one FindIt-Setup.exe
#define AppName "FindIt"
#define AppVersion "2.0.0"

[Setup]
AppId={{B7E3C1A4-5F2D-4E88-9A31-F1ND17000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=FindIt
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=FindIt-Setup
SetupIconFile=findit.ico
UninstallDisplayIcon={app}\FindIt.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "explorermenu"; Description: "Add ""Search with FindIt"" to the Explorer right-click menu (folders and drives)"; GroupDescription: "Windows integration:"
Name: "startup"; Description: "Start FindIt (minimized in the tray) when I sign in to Windows"; GroupDescription: "Windows integration:"; Flags: unchecked

[Files]
Source: "dist\FindIt\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\FindIt.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\FindIt.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\Directory\shell\FindIt"; ValueType: string; ValueData: "Search with FindIt"; Tasks: explorermenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\shell\FindIt"; ValueName: "Icon"; ValueType: string; ValueData: "{app}\FindIt.exe"; Tasks: explorermenu
Root: HKA; Subkey: "Software\Classes\Directory\shell\FindIt\command"; ValueType: string; ValueData: """{app}\FindIt.exe"" --path ""%1"""; Tasks: explorermenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\FindIt"; ValueType: string; ValueData: "Search with FindIt"; Tasks: explorermenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\FindIt"; ValueName: "Icon"; ValueType: string; ValueData: "{app}\FindIt.exe"; Tasks: explorermenu
Root: HKA; Subkey: "Software\Classes\Directory\Background\shell\FindIt\command"; ValueType: string; ValueData: """{app}\FindIt.exe"" --path ""%V"""; Tasks: explorermenu
Root: HKA; Subkey: "Software\Classes\Drive\shell\FindIt"; ValueType: string; ValueData: "Search with FindIt"; Tasks: explorermenu; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Drive\shell\FindIt\command"; ValueType: string; ValueData: """{app}\FindIt.exe"" --path ""%1"""; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "FindIt"; ValueType: string; ValueData: """{app}\FindIt.exe"" --background"; Tasks: startup; Flags: uninsdeletevalue

[Run]
Filename: "{app}\FindIt.exe"; Description: "Launch FindIt"; Flags: nowait postinstall skipifsilent
