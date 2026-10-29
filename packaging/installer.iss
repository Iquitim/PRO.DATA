; Inno Setup: instalador do PRO.DATA (spec 008, RF-805).
; Compilado por packaging/build.py, que passa /DAppVersion=... e /DSourceDir=...

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\PRO.DATA"
#endif

[Setup]
AppId={{6C1C7E0B-4F9B-4B2A-9C1E-7E3B9D2A5F10}
AppName=PRO.DATA
AppVersion={#AppVersion}
AppVerName=PRO.DATA {#AppVersion}
AppPublisher=Grupo Protege
; Instalação por usuário: não pede administrador.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\PRO.DATA
DefaultGroupName=PRO.DATA
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\PRO.DATA.exe
SetupIconFile=prodata.ico
; Telas do instalador com a marca Grupo Protege (geradas por make_icon.py)
WizardImageFile=wizard-100.bmp,wizard-150.bmp,wizard-200.bmp
WizardSmallImageFile=wizard-small-100.bmp,wizard-small-150.bmp,wizard-small-200.bmp
OutputDir=..\dist
OutputBaseFilename=PRO.DATA-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PRO.DATA"; Filename: "{app}\PRO.DATA.exe"
Name: "{group}\Desinstalar PRO.DATA"; Filename: "{uninstallexe}"
Name: "{userdesktop}\PRO.DATA"; Filename: "{app}\PRO.DATA.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PRO.DATA.exe"; Description: "Abrir o PRO.DATA agora"; Flags: nowait postinstall skipifsilent

; Os dados do usuário ficam em %LOCALAPPDATA%\PRO.DATA (fora de {app}) e não são
; removidos na desinstalação: fluxos, datasets e conexões sobrevivem a reinstalações.
