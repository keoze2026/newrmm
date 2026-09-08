# Building the endpoint agent

One codebase, three builds. PyInstaller cannot cross-compile, so each build runs
on the platform it targets.

```bash
python -m pip install -r agent/requirements.txt pyinstaller
cd agent
python build.py
```

| Platform | Output | Notes |
| --- | --- | --- |
| Linux | `agent/dist/rmm-agent` | Built and run — 23 MB, joins a session and streams |
| Windows | `agent/dist/rmm-agent.exe` | Not built yet — no Windows machine here |
| macOS | `agent/dist/rmm-agent` | Not built yet — no Mac here |

`--windowed` hides the console window; `--app` on macOS produces a `.app`
bundle, which the permission prompts need.

## Windows

```powershell
py -m pip install -r agent\requirements.txt pyinstaller
cd agent
py build.py
```

The agent marks itself DPI-aware at startup. Without that, a display at 125% or
150% scaling is captured at the smaller logical size and every injected click
lands at the wrong place — so this matters on most modern laptops.

The `.exe` is unsigned, so SmartScreen warns on first run: **More info → Run
anyway**. Signing is Phase 6.

## macOS

```bash
python3 -m pip install -r agent/requirements.txt pyinstaller
cd agent
python3 build.py --app
```

macOS needs **two separate permissions**, and grants neither by default:

| Permission | Without it | Where |
| --- | --- | --- |
| Screen Recording | Capture returns a blank or desktop-only image | System Settings → Privacy & Security → Screen Recording |
| Accessibility | Mouse and keyboard control silently do nothing | System Settings → Privacy & Security → Accessibility |

Screen Recording **only takes effect after the agent is restarted** — macOS does
not apply it to a running process. `rmm-agent status` reports both, so run that
first and fix anything that says `NOT GRANTED`.

Build with `--app`: the prompts are attributed to the bundle identifier, so a
bare binary run from a terminal asks on the terminal's behalf instead, and the
grant does not follow the agent.

Gatekeeper will refuse an unsigned build downloaded from elsewhere. For testing,
build on the machine, or clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine dist/rmm-agent
```

Signing and notarisation are Phase 6.

## Linux

```bash
python3 -m pip install -r agent/requirements.txt pyinstaller
cd agent
python3 build.py
```

Needs `python3-tk` for the consent dialog and clipboard, and a tray backend
(`gir1.2-appindicator3-0.1`). **X11 only** for now: on Wayland, capture goes
through the XDG portal and XTest input injection is usually refused. The agent
detects the session type and says so in `status`.

## Checking a build

```bash
./dist/rmm-agent status
```

Every line should report a real capability — `capture: screen`, `input:
available`, `tray: available`, `clipboard: available`, monitors with their real
sizes and origins. Anything reporting `unavailable` or `NOT GRANTED` will fail
in a session.
