# Phase 2 checkpoint — Windows endpoint

The specification's P2 gate:

> A Windows endpoint connects, streams a live screen, and is controllable;
> tray + consent show. **End-to-end tested on a real Windows machine.**

Everything below has to pass **on the Windows machine**. Nothing in this
repository can claim P2 until it does — the code has only ever run on Linux.

## Before you start

The Windows machine and the relay machine must be on the same network.

| Thing | Value |
| --- | --- |
| Relay host | `192.168.1.49` (this Linux machine) |
| Relay port | `8000` |
| Console | `http://192.168.1.49:5173` |

Check the Windows box can reach the relay — in PowerShell:

```powershell
curl.exe http://192.168.1.49:8000/health
```

Expect `{"status":"ok",...}`. If it hangs, the Linux firewall is blocking 8000:

```bash
sudo ufw allow 8000/tcp     # on the Linux machine
```

## 1. Install the agent on Windows

Python 3.11+ from python.org (tick **Add python.exe to PATH**), then:

```powershell
git clone <this repo>            # or copy the agent\ folder across
cd "new rmm"
py -m pip install -r agent\requirements.txt
```

## 2. Confirm the machine's capabilities

```powershell
cd agent
py -m rmm_agent status
```

- [ ] `platform` reads `windows`
- [ ] `capture` reads `screen` (not `synthetic`)
- [ ] `monitors` matches how many displays are attached
- [ ] `input` reads `available`
- [ ] `tray` reads `available`

## 3. Create a session in the console

On any machine, open `http://192.168.1.49:5173`, sign in, click **Create +**,
and note the 8-character code.

## 4. Join from Windows

```powershell
py -m rmm_agent join --relay ws://192.168.1.49:8000 --code <CODE> --verbose
```

- [ ] A tray icon appears in the Windows notification area
- [ ] A Windows notification says a session was requested
- [ ] A **consent dialog** appears asking to allow the session
- [ ] The console still shows *"Your guest has not joined yet…"* while the
      dialog is open — **nothing is shared before you answer**

Click **Deny** first:

- [ ] The agent reports consent denied and stops
- [ ] The console never shows a preview
- [ ] The session's **Logs** tab records `session.consent_denied`

Now create a fresh session, join again, and click **Allow**:

- [ ] The tray icon turns green and its tooltip says the screen is being shared
- [ ] A notification says the session started
- [ ] The console row's indicator turns **green**
- [ ] The waiting line flips to *"Your guest has joined."*
- [ ] A **LIVE preview** of the Windows desktop appears

## 5. The checkpoint itself

Click **Join** in the console to open the viewer.

- [ ] The Windows desktop renders live on the canvas
- [ ] The top bar shows the Windows machine name and a non-zero `fps · kbps`
- [ ] **Mouse:** moving the pointer in the viewer moves the Windows cursor to
      the matching place; clicks land on the right thing — try opening the Start
      menu and clicking a specific tile
- [ ] **Keyboard:** open Notepad on Windows through the viewer and type; the
      characters appear
- [ ] Right-click opens the Windows context menu
- [ ] Scrolling scrolls the Windows window under the cursor
- [ ] **Letterboxing:** resize the browser window so the canvas is letterboxed
      (black bars), then click a known target — it must still land correctly
- [ ] **Multi-monitor** (if the machine has more than one): the monitor
      switcher lists them and switching changes the streamed display
- [ ] **View-only:** toggling to View stops input reaching Windows
- [ ] **Reconnect:** unplug the network or stop the relay for ~20 seconds; the
      agent reports reconnecting and the session recovers when it returns

## 6. System info and audit

- [ ] The **System info** tab shows the real Windows hostname, version, user,
      IP, CPU, cores and memory
- [ ] The **Logs** tab shows `session.guest_attached`, `session.consent_granted`
      and `session.guest_joined`

## 7. Ending

- [ ] **End session and quit** in the tray menu stops the session
- [ ] The console indicator returns to grey
- [ ] `session.guest_left` appears in the Logs tab

## Known not to work in Phase 2

These are later phases and must **not** be treated as failures here:

- Privacy blank (eye-slash) — logged by the agent, blanks nothing. **Phase 5.**
- Terminal, Files, Send/Get file — labelled in the UI as unavailable. **Phase 4.**
- No installer, no auto-start, no code signing. **Phase 6.** SmartScreen will
  warn if you build the `.exe` with `agent\build_windows.py`.

## Reporting back

Tell me which boxes failed and paste the relevant lines from
`%APPDATA%\RMMAgent\agent.log`. Anything that fails is a per-Windows fix and
ships to Windows only.
