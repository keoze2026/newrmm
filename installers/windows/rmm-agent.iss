; Inno Setup definition for the Windows endpoint agent.
;
; Written for people who are not technical. They download this, double-click it,
; and that is all: no admin rights, no pages of options, nothing to type. When it
; finishes it opens the agent by itself, using the session code that is part of
; the file name it was downloaded as (rmm-agent-setup-ABCD1234.exe). The agent
; then asks for permission before anything is shared.

#define AppName "RMM Agent"
#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif

[Setup]
AppId={{6B1D4E52-8C3A-4F0B-9A47-2E5D7C91B3A8}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={autopf}\RMM Agent
DefaultGroupName={#AppName}
; Per-user: installs without administrator rights, so it works on a locked-down
; work laptop and never shows a permission prompt.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\agent\dist
OutputBaseFilename=rmm-agent-setup
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
UninstallDisplayName={#AppName}
; Nothing to choose, so nothing to click through.
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes

[Files]
Source: "..\..\agent\dist\rmm-agent-windows.exe"; DestDir: "{app}"; DestName: "rmm-agent.exe"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\RMM Agent"; Filename: "{app}\rmm-agent.exe"
Name: "{autodesktop}\RMM Agent"; Filename: "{app}\rmm-agent.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath('{app}')

[Run]
; Opens the agent as soon as it is installed. runasoriginaluser keeps it running
; as the person at the keyboard, not as whoever launched the installer.
Filename: "{app}\rmm-agent.exe"; Parameters: "{code:LaunchArgs}"; \
    Flags: nowait runasoriginaluser skipifsilent

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  Existing: string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Existing) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(ExpandConstant(Param)) + ';',
                ';' + Uppercase(Existing) + ';') = 0;
end;

function IsCodeChar(C: Char): Boolean;
begin
  Result := ((C >= 'A') and (C <= 'Z')) or ((C >= '0') and (C <= '9'));
end;

{ The code is carried in the file name: rmm-agent-setup-ABCD1234.exe, possibly
  with " (1)" added by the browser. A plain rmm-agent-setup.exe has none, and
  the agent then simply asks for one. }
function CodeFromFileName(): string;
var
  Name, Prefix, Candidate: string;
  Dot, Space, I: Integer;
begin
  Result := '';
  Prefix := 'rmm-agent-setup-';
  Name := ExtractFileName(ExpandConstant('{srcexe}'));

  Dot := Pos('.', Name);
  if Dot = 0 then exit;
  Name := Copy(Name, 1, Dot - 1);

  Space := Pos(' ', Name);
  if Space > 0 then Name := Copy(Name, 1, Space - 1);

  if Pos(Prefix, Name) <> 1 then exit;
  Candidate := Uppercase(Copy(Name, Length(Prefix) + 1, Length(Name)));

  if (Length(Candidate) < 4) or (Length(Candidate) > 16) then exit;
  for I := 1 to Length(Candidate) do
    if not IsCodeChar(Candidate[I]) then exit;

  Result := Candidate;
end;

function LaunchArgs(Param: string): string;
var
  Code: string;
begin
  Code := CodeFromFileName();
  if Code = '' then
    Result := 'start'
  else
    Result := 'start --code ' + Code;
end;
