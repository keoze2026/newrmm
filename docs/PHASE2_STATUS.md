# Phase 2 — what is built, what is proven, what is not

## Built

| Piece | Where |
| --- | --- |
| Agent package with CLI (`join`, `enrol`, `status`) | `agent/rmm_agent/` |
| Consent surface — dialog, tray notification, terminal fallback | `agent/rmm_agent/consent.py` |
| Tray presence indicator with live state and an End-session item | `agent/rmm_agent/tray.py` |
| Screen capture, multi-monitor, adaptive quality and frame rate | `agent/rmm_agent/capture.py` |
| Input injection — mouse, keyboard, scroll, full key mapping | `agent/rmm_agent/remote_input.py` |
| Reconnect with exponential backoff | `agent/rmm_agent/session.py` |
| Unattended enrolment and device presence | `agent/rmm_agent/device.py` |
| Consent gate enforced by the relay, not just the agent | `relay/app/api/ws.py` |
| Per-device authentication for unattended sessions | `relay/app/api/ws.py` |
| Windows executable build | `agent/build_windows.py` |

## Proven on Linux

`tests/e2e/p2_session_flow.py` — 13/13 against a live relay:

- Attaching does not join a session until consent is answered
- **Frames sent before consent never reach the operator** — the relay drops them
- Granting consent joins the session and makes it active; frames then flow
- Denying consent leaves the session unjoined, and the denial is audited
- Attach, consent and join are all on the audit trail
- An unattended session refuses a guest with no device credentials
- The enrolled device is accepted with its secret; a wrong secret is refused
- An enrolled device reports itself online, and offline when its socket drops

`relay/tests/` — 33/33, including two tests that put a session row into the
state a compromised agent would want (`guest_connected` true, consent pending)
and confirm the API still reports the guest as absent.

`tests/e2e/console_appendix_a.py` — the console suite now runs against the real
agent rather than a stand-in.

## NOT proven — this is the open item

**Nothing has run on Windows.** The P2 checkpoint requires it:

> A Windows endpoint connects, streams a live screen, and is controllable;
> tray + consent show. End-to-end tested on a real Windows machine.

Specifically unverified on Windows: that `mss` captures the desktop, that
`pynput` drives SendInput correctly for clicks and keystrokes, that `pystray`
shows a tray icon in the notification area, that the tkinter consent dialog
appears above other windows, and that PyInstaller produces a working `.exe`.

Work through `docs/PHASE2_WINDOWS_CHECKLIST.md` on the Windows machine. Until
every box there passes, Phase 2 is not done.

## Not in Phase 2 (do not treat as failures)

- Privacy blank — received and logged, blanks nothing. **Phase 5.**
- Terminal, Files, clipboard, file transfer. **Phase 4.**
- macOS and Linux endpoint parity. **Phase 3.**
- Installer, auto-start, code signing. **Phase 6.**
