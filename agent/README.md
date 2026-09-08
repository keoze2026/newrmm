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
| `{"type":"blank","on":true}` | Privacy blank - see below |

Coordinates are normalised 0..1, so the guest lands on the right pixel no matter
how the operator's canvas is scaled or letterboxed.

## Tools

The agent also serves the operator's tool panels:

| Message | Effect |
| --- | --- |
| `{"type":"terminal","action":"open\|input\|resize\|close"}` | A shell on the endpoint - a real pty on POSIX, pipes around PowerShell on Windows |
| `{"type":"files","action":"list\|get\|put"}` | Browse a directory, retrieve a file in chunks, or receive one |
| `{"type":"clipboard","action":"get\|set"}` | Read or write the endpoint clipboard |

The clipboard keeps one hidden Tk window alive for the life of the agent: on
X11 the clipboard belongs to a live window, so a root created and destroyed per
call would lose the contents immediately.

## Privacy blank

What the agent can do depends on whether the OS can hide a window from its own
screen capture. The agent reports which mode it will use, so the console can say
so rather than implying something it cannot deliver.

| Platform | Mode | What happens |
| --- | --- | --- |
| Windows | `capture-excluded` | A black window marked `WDA_EXCLUDEFROMCAPTURE`. The guest sees black; the operator keeps a live view and control. |
| macOS | `capture-excluded` | The same through `NSWindowSharingNone`. Needs pyobjc; without it the agent falls back to a guest lock. |
| Linux | `guest-lock` | No universal capture-exclusion exists, so the screen is blacked **and local input is blocked**. The operator's view goes black too — it locks the machine rather than hiding the operator's work. |

If capture-exclusion is asked for and the OS refuses, the agent falls back to a
guest lock rather than pretending the operator's work is hidden.

**Safety.** A blank that outlives its session would leave someone at a black
screen they cannot dismiss, so it is released when the session ends or the
connection drops. `--blank-watchdog SECONDS` adds a hard time limit on top.
`--blank-no-input-block` blanks without blocking input and exists only so the
test suite cannot lock the machine it runs on.

## What this is not

- There is no installer, service or auto-start yet, and no code signing (Phase 6).
- The Windows path does not use the native Rust capture engine the specification
  describes; it keeps mss and relies on the compositor honouring the exclusion
  flag. Untested on Windows.
