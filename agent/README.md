# Endpoint agent

Joins a session, asks the person at the keyboard for consent, then streams the
screen and applies the operator's mouse and keyboard.

Nothing is captured before consent is granted — and the relay enforces that
independently, dropping any frame that arrives before a decision is recorded.

## Install

```bash
python -m pip install -r agent/requirements.txt
```

Linux also needs a tray backend and Tk for the consent dialog:
`sudo apt install python3-tk gir1.2-appindicator3-0.1`

## Use

```bash
# What this machine supports
python -m rmm_agent status

# Attended: join with the code the operator gave the user
python -m rmm_agent join --relay ws://<relay-host>:8000 --code ABCD1234

# Unattended: store device credentials and stay reachable
python -m rmm_agent enrol --relay ws://<relay-host>:8000 \
    --device-id <uuid> --secret <enrolment-secret>
```

### Options for `join`

| Option | Effect |
| --- | --- |
| `--fps`, `--quality` | Frame rate and JPEG quality |
| `--budget-kbps N` | Adapt quality and frame rate to a bandwidth budget |
| `--device-id`, `--secret` | Required for an unattended session |
| `--synthetic` | Stream a generated test image; needs no display |
| `--no-tray` | Run without the tray icon |
| `--no-input` | Log operator input instead of applying it (tests) |
| `--auto-consent` | Skip the consent prompt — **testing only** |

State and logs live in `%APPDATA%\RMMAgent` on Windows,
`~/Library/Application Support/RMMAgent` on macOS, and
`~/.local/state/RMMAgent` on Linux.

## Build a Windows executable

On the Windows machine:

```
py -m pip install -r agent/requirements.txt pyinstaller
py agent/build_windows.py
```

Produces `agent/dist/rmm-agent.exe`, unsigned — SmartScreen will warn on first
run. Signed installers are Phase 6.

## Protocol

Connects to `ws://<relay>/ws/guest/<CODE>` (plus `?device_id=&secret=` when
unattended) and sends one JSON hello:

```json
{"host_name": "...", "system_info": {...}, "monitors": [...], "agent_version": "0.2.0"}
```

Then a consent decision, and only then binary JPEG frames:

```json
{"type": "consent", "granted": true}
```

It receives JSON control messages:

| Message | Meaning |
| --- | --- |
| `{"type":"input","kind":"mouse","action":"move\|down\|up","x":0..1,"y":0..1,"button":"left"}` | Pointer, normalised |
| `{"type":"input","kind":"key","action":"down\|up","key":"a"}` | Keyboard |
| `{"type":"input","kind":"scroll","dx":0,"dy":0}` | Wheel |
| `{"type":"monitor","index":0}` | Switch captured display |
| `{"type":"blank","on":true}` | Privacy blank (logged; implemented in Phase 5) |

Coordinates are normalised 0..1, so the guest lands on the right pixel no matter
how the operator's canvas is scaled or letterboxed.

## What this is not

- The privacy blank is **not** implemented (Phase 5). The message is received
  and logged; no screen is blanked.
- File transfer, terminal and clipboard are **not** implemented (Phase 4).
- There is no installer, service or auto-start yet, and no code signing (Phase 6).
