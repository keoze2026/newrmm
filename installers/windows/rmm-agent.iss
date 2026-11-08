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
; The silent watchdog check (rmm_agent/watchdog_check.py) - must land in the
; same directory as rmm-agent.exe itself, since that is where it looks for it.
Source: "..\..\agent\dist\rmm-agent-watchdog.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\RMM Agent"; Filename: "{app}\rmm-agent.exe"
Name: "{autodesktop}\RMM Agent"; Filename: "{app}\rmm-agent.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Registry]
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; \
    ValueData: "{olddata};{app}"; Check: NeedsAddPath('{app}')

[UninstallRun]
; Uninstalling must leave nothing running and nothing that starts again. The
; agent creates its restart entry and watchdog task itself at run time, so the
; installer never knew about them and used to leave them behind (scan finding).
; The watchdog's scheduled task (autostart.WATCHDOG_TASK) goes first, so it
; cannot start the agent again in between; then both programs are stopped, or
; their files could not be removed.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN RMMAgentWatchdog /F"; \
    Flags: runhidden waituntilterminated; RunOnceId: "DeleteWatchdogTask"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM rmm-agent-watchdog.exe"; \
    Flags: runhidden waituntilterminated; RunOnceId: "StopWatchdog"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM rmm-agent.exe"; \
    Flags: runhidden waituntilterminated; RunOnceId: "StopAgent"

[UninstallDelete]
; The agent's own state (config.state_dir): enrolment.json with the device
; secret, the saved session, session secrets, logs and the pid file.
Type: filesandordirs; Name: "{userappdata}\RMMAgent"

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

{ Takes the install directory back out of the user's PATH, which the
  [Registry] entry above added. Only that one entry is removed. }
procedure RemoveFromPath(Dir: string);
var
  Existing, Rebuilt, Item, Upper: string;
  Sep: Integer;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Existing) then exit;
  Upper := Uppercase(Dir);
  Rebuilt := '';
  Existing := Existing + ';';
  while Length(Existing) > 0 do
  begin
    Sep := Pos(';', Existing);
    Item := Copy(Existing, 1, Sep - 1);
    Existing := Copy(Existing, Sep + 1, Length(Existing));
    if (Item <> '') and (Uppercase(Item) <> Upper) and (Uppercase(Item) <> Upper + '\') then
    begin
      if Rebuilt <> '' then Rebuilt := Rebuilt + ';';
      Rebuilt := Rebuilt + Item;
    end;
  end;
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Rebuilt);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    { The restart-at-login entry the agent writes (autostart.RUN_NAME). }
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RMMAgentResume');
    RemoveFromPath(ExpandConstant('{app}'));
  end;
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
