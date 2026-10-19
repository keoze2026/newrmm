; Inno Setup definition for the Windows endpoint agent.
;
; Section 8: "installs without manual steps". Installs the agent under Program
; Files and adds it to PATH. Nothing is started and nothing runs on its own: the
; agent is launched when someone joins a session, and it asks for consent first.

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
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\agent\dist
OutputBaseFilename=rmm-agent-setup
Compression=lzma2
SolidCompression=yes
ChangesEnvironment=yes
UninstallDisplayName={#AppName}

[Files]
Source: "..\..\agent\dist\rmm-agent-windows.exe"; DestDir: "{app}"; DestName: "rmm-agent.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath('{app}')

[Code]
function NeedsAddPath(Param: string): Boolean;
var
  Existing: string;
begin
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
                             'Path', Existing) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Uppercase(ExpandConstant(Param)) + ';',
                ';' + Uppercase(Existing) + ';') = 0;
end;
