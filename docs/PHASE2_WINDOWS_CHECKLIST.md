# Phase 2 checkpoint — Windows endpoint

The specification's P2 gate:

> A Windows endpoint connects, streams a live screen, and is controllable;
> tray + consent show. **End-to-end tested on a real Windows machine.**

Everything below has to pass **on the Windows machine**. Nothing in this
repository can claim P2 until it does — the code has only ever run on Linux.

## Which commands run where

Everything in this document runs **on the Windows machine, in PowerShell** —
except where a block is explicitly labelled *on the Linux machine*. `py` and
`curl.exe` are Windows commands; they do not exist on Linux.

## Before you start

Both machines must be on the same network. The Linux machine's address changes
with the network it joins — get the current one there:

```bash
# on the Linux machine
ip route get 8.8.8.8 | sed -n 's/.*src \([0-9.]*\).*/\1/p'
```

At the time of writing it is **172.27.16.138**, so:

| Thing | Value |
| --- | --- |
| Relay | `http://172.27.16.138:8000` / `ws://172.27.16.138:8000` |
| Console | `http://172.27.16.138:5173` |

Substitute your own address if it has changed.

Check the Windows box can reach the relay — **in PowerShell on Windows**:

```powershell
curl.exe http://172.27.16.138:8000/health
```

Expect `{"status":"ok",...}`. If it hangs or refuses:

```bash
# on the Linux machine
sudo ufw allow 8000/tcp
sudo ufw allow 5173/tcp
```

Both services must be listening on all interfaces, not just localhost:

```bash
# on the Linux machine - both lines should show 0.0.0.0 or *
ss -ltn | grep -E ':(8000|5173)'
```

## 1. Get the agent onto the Windows machine

Pick whichever is easiest:

- **Git:** clone this repository on Windows.
- **Copy:** copy the whole `agent\` folder across on a USB stick or a share.
- **Share from Linux:** run `python3 -m http.server 8081` in the project
  directory on Linux, then on Windows browse to
  `http://172.27.16.138:8081` and download the `agent` folder.

Then install Python 3.11+ from python.org — **tick "Add python.exe to PATH"** —
and in PowerShell:

```powershell
cd <wherever you put it>
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

## 3. Create a session

Either open `http://172.27.16.138:5173` in a browser, sign in
(`admin@example.com` / `ChangeMe123!`), and click **Create +** —

or, faster, **on the Linux machine**:

```bash
./scripts/new_session.sh
```

which prints the code and the exact command to paste on Windows.

## 4. Join from Windows

Replace `<CODE>` with the actual 8-character code — the angle brackets are not
part of it:

```powershell
py -m rmm_agent join --relay ws://172.27.16.138:8000 --code <CODE> --verbose
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

If `py -m rmm_agent` reports *No module named rmm_agent*, you are not in the
folder that contains `rmm_agent\` — `cd` into `agent\` first.
