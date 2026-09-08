# Project status

Updated after every change. Read this before claiming anything works.

## Where the build is

Phase 1 (Foundation) is complete. The operator console matches **Appendix A** of
the specification. **Phase 2 is code-complete and fully verified on Linux, but
its checkpoint is NOT passed**, because the checkpoint requires a real Windows
machine and nothing here has run on Windows.

The endpoint agent now exists as a real package (`agent/rmm_agent/`) with a
consent surface, tray presence, capture, input injection, reconnect and
unattended enrolment. The old `dev_guest.py` stand-in has been removed; the
tests drive the real agent.

Phase 3 and Phase 4 are code-complete for all three platforms. Linux is verified
end to end on this machine; the Windows and macOS support is written but has not
run on that hardware, and will be tested once the relay is deployed and the
agents are built on those machines.

`docs/BUILDING_AGENTS.md` covers building on each OS; `docs/DEPLOYMENT.md`
covers standing the relay up somewhere the other machines can reach.

## What works, and how it was verified

| Capability | Verified by |
| --- | --- |
| Operator login, Argon2 hashing, JWT bearer tokens | `relay/tests/test_auth.py`, Appendix A test A.1 |
| Wrong password rejected inline; Enter submits the login form | Appendix A test A.1 |
| Four-column layout: icon rail, section panel, session list, detail panel | Appendix A test A.2 |
| Session list: Join/Edit/Delete/More, select-all, search, rows with Host and indicator | Appendix A tests A.2, A.3 |
| Connection indicator turns green when the guest is actually connected | Appendix A test A.3 |
| Ten detail tabs in the specified order; active tab has the #2F6FE4 left border | Appendix A test A.4 |
| Session tab: editable name with pencil, Invite via Code/Link, code card, copy | Appendix A test A.5 |
| Rename changes the name and never the join code | `relay/tests/test_session_console.py`, Appendix A test A.5 |
| Waiting line flips to "Your guest has joined."; Join enables; LIVE preview appears | Appendix A test A.5 |
| System info shows the endpoint's real hostname, OS, user, IP, CPU, cores, memory | Appendix A test A.6 |
| Logs show the server-side audit trail scoped to that session | `relay/tests/test_session_console.py`, Appendix A test A.6 |
| Session history renders per machine | `relay/tests/test_session_console.py`, Appendix A test A.6 |
| Chat, Tools and Locate are present and clearly labelled as not implemented | Appendix A test A.6 |
| Viewer: machine name, live dot, live fps · kbps readout | Appendix A test A.7 |
| Viewer toolbar carries every control the specification lists | Appendix A test A.7 |
| Guest screen renders live on the canvas, letterboxed, never stretched | Appendix A test A.7 |
| Pointer input reaches the guest at the right coordinates when letterboxed | Appendix A test A.7 — the guest logs the coordinates it was told, and the test asserts them |
| Blank toggle reaches the guest | Appendix A test A.7 — asserted against the guest's own log |
| Controlling / View-only toggle, zoom, annotate, clear, monitor switcher, End | Appendix A test A.7 |
| Single-page app: no panel navigation ever reloads the page | Appendix A test A.2 |
| Device enrolment; the secret is shown once and stored only as an Argon2 hash | `relay/tests/test_devices.py` (API only — see below) |
| Audit log is append-only — the database rejects UPDATE and DELETE | `relay/tests/test_audit.py` |
| Compose stack builds, migrates on start, serves console and API through nginx | Stack brought up and the browser suite re-run against it |
| Endpoint agent attaches, reports host details, and asks for consent | `tests/e2e/p2_session_flow.py`, Appendix A suite run against the real agent |
| **Nothing is captured or relayed before consent is granted** | `tests/e2e/p2_session_flow.py` — frames sent before consent are asserted never to reach the operator |
| Granting consent joins the session; denying leaves it unjoined | `tests/e2e/p2_session_flow.py` |
| Attach, consent granted, consent denied, join and leave are all audited | `tests/e2e/p2_session_flow.py` |
| Presence cannot be faked by a forged row — consent is required | `relay/tests/test_session_console.py` |
| Unattended sessions require per-device credentials; a wrong secret is refused | `tests/e2e/p2_session_flow.py` |
| An enrolled device reports online, and offline when its socket drops | `tests/e2e/p2_session_flow.py` |
| Agent capture, input injection and tray all available on Linux | `python -m rmm_agent status` |
| Operator coordinates map correctly on Retina, DPI-scaled and secondary displays | `agent/tests/test_input_mapping.py` — the cases this hardware cannot reproduce |
| Reported display geometry matches the captured frame | `tests/e2e/p3_linux_endpoint.py` |
| The build script produces a standalone binary that joins a session and streams | Built here: `agent/dist/rmm-agent`, run and connected, with the native module bundled |
| **The native C capture module (X11 XShm) is the capture path in use, not the mss fallback** | `tests/e2e/p3_linux_endpoint.py` asserts the backend is `native-x11-shm` |
| The native module is measurably faster than the fallback | 164 fps raw at 1920x1200, 62 fps end to end, against about 40 fps on mss |
| Privacy blank: the captured screen really goes black, and comes back | `tests/e2e/p5_privacy_blank.py` — mean luminance 73 → 0.1 → 73 |
| The agent keeps streaming and stays online across repeated blank toggles | `tests/e2e/p5_privacy_blank.py` (the P5 checkpoint) |
| The endpoint reports guest-lock rather than claiming capture-exclusion | `tests/e2e/p5_privacy_blank.py`, `agent/tests/test_privacy.py` |
| The overlay is proven to cover the whole screen, and refuses to claim success otherwise | `agent/tests/test_privacy.py` |
| The guest-lock blocks local input, and always releases it | `agent/tests/test_privacy_input_block.py` (in a throwaway process with a watchdog) |
| A blank never outlives its session, and a watchdog releases it regardless | `tests/e2e/p5_privacy_blank.py`, `agent/tests/test_privacy.py` |
| Ending a session disconnects the endpoint, so capture actually stops | `relay/tests/test_session_console.py`, `tests/e2e/p5_privacy_blank.py` |
| Agent reconnects with exponential backoff after a drop | `agent/rmm_agent/session.py` (code path exercised; drop scenario is on the Windows checklist) |
| **Real** screen capture of the Linux desktop, sustaining 41 fps | `tests/e2e/p3_linux_endpoint.py` |
| **Real** pointer injection lands on the right pixel of the real screen | `tests/e2e/p3_linux_endpoint.py` — the pointer is moved and read back |
| **Real** keystroke injection is delivered to X | `tests/e2e/p3_linux_endpoint.py` — a listener receives the injected key |
| Capture quality and frame rate adapt to a bandwidth budget | `tests/e2e/p3_linux_endpoint.py` |
| Remote terminal: a real pty, output streamed back, state kept between commands | `tests/e2e/p4_tools.py`, `tests/e2e/p4_console_tools.py` |
| File transfer both ways, byte-for-byte, chunked at 256 KB | `tests/e2e/p4_tools.py` |
| Missing files and unreadable directories report errors instead of hanging | `tests/e2e/p4_tools.py` |
| Clipboard sync round-trips text between operator and endpoint | `tests/e2e/p4_tools.py`, `tests/e2e/p4_console_tools.py` |
| Terminal keystrokes do not leak to the guest screen | `tests/e2e/p4_console_tools.py` |

Last run: **33/33 pytest tests**, **13/13 Phase 2 session-flow checks**, and
**32/32 Appendix A browser checks** — the browser suite now driven by the real
endpoint agent, against a live relay, PostgreSQL 17 and Redis 8 on Linux.
Screenshots in `docs/screenshots/`.

Real bugs surfaced by these runs, all fixed:

- The relay reported a guest as connected the moment its socket attached, before
  consent was answered. Presence is now gated on consent, and a regression test
  puts a session row into exactly the state a compromised agent would want and
  asserts the API still reports the guest as absent.
- The agent's CLI joined its worker thread with a 15-second timeout when run
  with `--no-tray`, so the agent quit fifteen seconds after starting. It now
  waits for the event loop properly.
- The clipboard created and destroyed a Tk root per call. On X11 the clipboard
  belongs to a live window, so the contents vanished the moment the root exited
  and every read came back empty. One hidden root now lives for the life of the
  agent.
- The terminal renderer treated the trailing carriage return of a pty's CR LF
  line ending as "return to column zero" and blanked every line. CR LF is
  normalised before that logic runs.
- Switching from the Terminal panel to Files killed the shell, because the panel
  closed it on unmount. The viewer owns the shell's lifetime now.

## What does NOT work yet

- **Phase 2's checkpoint is not passed.** The specification requires the core
  session to be "end-to-end tested on a real Windows machine". No code in this
  repository has run on Windows. Unverified there: that `mss` captures the
  desktop, that `pynput` drives SendInput for clicks and keystrokes, that
  `pystray` shows a tray icon, that the consent dialog appears above other
  windows, and that PyInstaller produces a working `.exe`.
- **The Windows (Rust) and macOS (Swift) native capture modules have not been
  compiled.** They were written against the real APIs — the `windows-capture`
  1.5 source was read to confirm every signature — but this machine has no
  Windows Rust target (no `rustup`, so `x86_64-pc-windows-*` cannot be added)
  and no Swift toolchain. Reading a crate is not compiling against it: expect
  to fix compile errors on first build.
- **macOS has not been run.** The support is written — Screen Recording and
  Accessibility checks, Retina coordinate mapping, a `.app` bundle build — but
  no Mac has executed a line of it.
- **Windows has not been run.** Same: DPI awareness, the per-OS hidden imports
  and the `.exe` build are written, not executed there.
- The agent has no installer, no service or auto-start, and no code signing.
  Phase 6. An `.exe` built with `agent/build_windows.py` is unsigned, so
  SmartScreen will warn.
- Chat, Tools and Locate are placeholders, labelled as such on screen.
- The Files panel browses from the endpoint user's home directory; there is no
  path entry box yet, so reaching an arbitrary directory means clicking through.
- The terminal renders colour and plain output, but is not a full terminal
  emulator: cursor addressing means full-screen programs such as `vim` or `top`
  will not display correctly.
- The privacy blank on **Windows and macOS is untested**. Both use the OS's
  capture-exclusion (`WDA_EXCLUDEFROMCAPTURE`, `NSWindowSharingNone`) and the
  agent falls back to a guest lock if the OS refuses — but no machine has run
  either path. On Windows the specification calls for a native Rust capture
  engine; this uses mss and relies on the compositor honouring the exclusion
  flag instead.
- macOS capture-exclusion needs pyobjc installed, or the agent guest-locks.
- The relay hub is single-process and in-memory, so a deployment must run one
  relay process. Moving fan-out onto Redis pub/sub is Phase 6.
- **The console no longer has Devices or Audit pages.** Appendix A's icon rail
  has one nav item, Support, so those views were removed to match. Device
  enrolment still works over the API (`POST /devices`) and the audit trail is
  visible per session in the Logs tab, but there is no longer a UI for enrolling
  a device or reading the whole audit log. Worth raising if that matters.
- Frames are whole-screen JPEG at a fixed quality. Changed-region streaming and
  adaptive quality (spec section 10) are not implemented.
- TLS is not configured. The compose stack serves plain HTTP; certificates are
  Phase 6.

## Environment this was built and tested on

- Linux (Parrot OS), Python 3.13.5, Node 24.20.0
- PostgreSQL 17 in a container on `127.0.0.1:55433` (the host's system Postgres
  cluster is present but fails to start; the container sidesteps it)
- Redis 8 on the host at `127.0.0.1:6379`
- Google Chrome drives the browser suite through Playwright

## How to revert

```bash
git checkout console-appendix-a # before the Phase 2 agent
git checkout p1-foundation      # before the Appendix A console
git checkout p0-docs            # before any code
```

To undo a database migration:

```bash
cd relay && ../.venv/bin/python -m alembic downgrade 0001_initial
```

## Change log

- **Native capture modules (specification §5 and §6).** The documentation
  requires a native capture module per OS, exposed to the agent as a Python
  module, and none had been built — the agent used mss everywhere. Now:
  Linux in **C** (X11 XShm via MIT-SHM, XRandR for monitor geometry, PipeWire
  compiled in when its headers are present), Windows in **Rust** (`windows-capture`
  / Windows.Graphics.Capture through PyO3), macOS in **Swift** (ScreenCaptureKit
  behind a C ABI, loaded with ctypes). All three present the same interface and
  `rmm_agent/native.py` loads whichever is built, falling back to mss — which
  is where `BUILD_PROMPT.md:35` puts it — when none is.

  This matters beyond speed: the privacy blank marks its black window excluded
  from capture, and only a compositor-level API honours that and keeps
  delivering the desktop behind it. A plain screen grab returns the black
  window, which is the exact failure §5 describes.

  The Linux module is built and verified here at 164 fps raw. The Windows and
  macOS modules cannot be compiled on this machine and are unverified.

- **P5 — Privacy blank.** Per-platform: capture-exclusion on Windows and macOS,
  and the guest-lock variant on Linux, where no universal exclusion exists. The
  agent reports which of the two it can deliver and the console says so plainly,
  including a confirmation before locking someone's screen. Verified on Linux
  against real capture: the frames the operator receives go from luminance 73 to
  0.1 and back, and the agent stays online across repeated toggles.

  Three bugs found while building it. The overlay was created at its natural
  size — 579x26 — because `-fullscreen` is only a request to the window manager,
  so the blank reported success while blanking nothing; it now forces the
  geometry and refuses to claim success if it still cannot cover the screen.
  Tk was being called from threads that did not own it, aborting the process.
  And **ending a session did not disconnect the endpoint**: the agent kept
  capturing and streaming after the session was marked ended, which section 9
  forbids — the relay now hangs up on both halves, and the agent retires
  cleanly rather than reconnecting to a session that is over.

- **P3 — Cross-platform core.** Per-OS setup and capability checks: Windows DPI
  awareness before capture, macOS Screen Recording and Accessibility checks,
  Linux X11-versus-Wayland detection. Operator input now maps through the
  display's logical geometry including its origin, so Retina, DPI-scaled and
  secondary monitors all land correctly — previously it used raw frame pixels,
  which is right only on an unscaled primary display. One `build.py` produces a
  standalone binary on any of the three platforms; the Linux one is built and
  proven. `status` reports monitors, permissions and session type.

- **P2 — Endpoint agent (Linux-verified; Windows checkpoint open).** Real agent
  package with `join`, `enrol` and `status` commands; consent dialog, tray
  presence and notifications; capture with multi-monitor and adaptive quality;
  input injection; reconnect with backoff; unattended enrolment and device
  presence. Relay now enforces the consent gate itself and authenticates
  unattended endpoints per device. Removed `dev_guest.py`; the tests drive the
  real agent. Windows verification is `docs/PHASE2_WINDOWS_CHECKLIST.md`.

- **Appendix A console.** Rebuilt the operator console to the exact layout,
  labels, order and behaviour of Appendix A: light theme on the specified
  palette, four-column layout, ten-tab detail panel, session tab with the code
  card and waiting states, and the full-screen viewer with a live canvas.
  Added the session transport (WebSocket guest and operator sockets with an
  in-process hub), session rename, per-session history and logs, and
  `agent/dev_guest.py` so the live path is genuinely testable.
  Removed the Devices and Audit console pages to match the specified icon rail.

- **P1 — Foundation.** Relay server (FastAPI, async SQLAlchemy, Alembic),
  operator auth, device enrolment, session model, append-only audit log with a
  database trigger enforcing immutability, health checks, console shell, compose
  stack and nginx config. Tagged `p1-foundation`.
