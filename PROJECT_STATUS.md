# Project status

Updated after every change. Read this before claiming anything works.

## Where the build is

Every phase is built. Phases 1 and 4 are complete and verified. Phases 2, 3 and
5 are complete and verified **on Linux only** — their checkpoints name Windows
and macOS, and no code has run on either. Phase 6 is built except for signed
installers, and the stack has never been deployed.

The open work is not writing code. It is running what exists on Windows and
macOS, procuring signing certificates, and deploying.

| Phase | Scope | State |
| --- | --- | --- |
| P1 | Relay, auth, session model, audit log, console shell | **Done, checkpoint passing** |
| — | Console rebuilt to Appendix A | **Done, 32/32 conformance** |
| P2 | Core session: enrol/connect, capture, control, tray, consent | Built and verified on Linux. **Windows checkpoint not run** |
| P3 | Cross-platform core | Linux verified. Windows and macOS **compile in CI**, never executed |
| P4 | Tools: file transfer, terminal, clipboard, multi-monitor, screenshot/zoom/annotate | **Done, verified** |
| P5 | Privacy blank | Linux guest-lock verified. Windows/macOS capture-exclusion **untested** |
| P6 | Hardening and release | CI, TLS, Redis fan-out, logging, security review, session expiry done. Linux `.deb` done. **Windows and macOS installers, signing and deployment open** |

## Test counts

| Suite | Count | What it covers |
| --- | --- | --- |
| `relay/tests` | 59 | API, database, consent gate, append-only audit, rate limiting, session expiry |
| `agent/tests` | 45 | Coordinate mapping, privacy blank, input block, tile encoder |
| `tests/e2e/console_appendix_a.py` | 32 | Appendix A conformance in a real browser |
| `tests/e2e/p2_session_flow.py` | 13 | Consent gate and device authentication |
| `tests/e2e/p3_linux_endpoint.py` | 12 | Real capture and real input injection |
| `tests/e2e/p4_tools.py` | 13 | Terminal, file transfer, clipboard |
| `tests/e2e/p4_console_tools.py` | 9 | The same tools driven through the console |
| `tests/e2e/p5_privacy_blank.py` | 15 | Blank on/off against real capture |
| `tests/e2e/p6_low_bandwidth.py` | 7 | Section 8's ~1 Mbps acceptance criterion |
| `tests/e2e/p6_reconnect.py` | 9 | Section 8's reconnect-after-drop criterion. Passing: the relay is killed under a running agent, which reconnects and streams again unaided |

CI runs the relay, agent and console suites on every push, and builds an agent
on a Windows, macOS and Linux runner. Both workflows are green.

## What works, and how it was verified

| Capability | Verified by |
| --- | --- |
| Operator login, Argon2 hashing, JWT bearer tokens | `relay/tests/test_auth.py`, Appendix A A.1 |
| Four-column console exactly as Appendix A specifies | `console_appendix_a.py` |
| Attended sessions: code, join link, guest landing page, connector download | `connector` tests, join page driven in a browser |
| Unattended enrolment with per-device credentials | `p2_session_flow.py` |
| **Nothing is captured or relayed before consent** | `p2_session_flow.py` — frames sent before consent are asserted never to arrive |
| Presence cannot be faked by a forged row | `relay/tests/test_session_console.py` |
| Ending a session disconnects the endpoint, so capture stops | `relay/tests/test_session_console.py`, `p5_privacy_blank.py` |
| Native C capture module is the capture path, not the mss fallback | `p3_linux_endpoint.py` asserts the backend |
| Real capture at 164 fps raw, 62 fps end to end | `p3_linux_endpoint.py` |
| Real pointer and keystroke injection reach X | `p3_linux_endpoint.py` |
| Coordinates map correctly on Retina, DPI-scaled and secondary displays | `agent/tests/test_input_mapping.py` |
| Remote terminal, file transfer both ways, clipboard sync | `p4_tools.py`, `p4_console_tools.py` |
| Privacy blank blacks the captured screen and restores it | `p5_privacy_blank.py` — luminance 143.8 → 0.1 → 143.1 |
| A blank never outlives its session; Escape always releases it | `agent/tests/test_privacy*.py` |
| Changed-region streaming fits a 1 Mbps link | `p6_low_bandwidth.py` — 398 kbps, 9.3 fps |
| Audit log is append-only, enforced by a database trigger | `relay/tests/test_audit.py` |
| Login and code probing are rate limited | `relay/tests/test_security.py` |
| All three agents build on their own platform | CI `agents.yml`, green |

## What does NOT work yet

- **Windows and macOS have never run the agent.** Both compile in CI. The
  consent surface, tray indicator, capture, input injection and privacy blank
  are all unproven there, and all are security-relevant. This is P2's and P3's
  checkpoint and P5's Windows/macOS half.
- **Windows installer is written but has never been built or run.**
  `installers/windows/rmm-agent.iss` (Inno Setup) installs the agent under
  Program Files and adds it to PATH; CI builds it as `rmm-agent-setup.exe`. It
  has not yet run in CI, and nothing has installed it on a Windows machine.
- **No macOS installer.** The macOS agent still ships as a zipped `.app`. A
  `.pkg` script was attempted and the writes were stopped by an automated safety
  filter, so none exists. Linux has a `.deb` (`installers/linux/build_deb.sh`).
- **Builds are unsigned.** Section 11 assumes certificates can be procured; they
  have not been. SmartScreen warns, and Gatekeeper refuses outright.
- **Never deployed.** The TLS config and compose overlay are written and
  unexercised.
- Chat, Tools and Locate are placeholders, labelled as such on screen.
- The terminal renders colour but is not a full emulator: `vim` and `top` will
  not display correctly.
- The Files panel browses from the endpoint user's home with no path entry box.
- The PipeWire capture path needs `libpipewire-0.3-dev` to compile in; without
  it the Linux module is X11 only, and Wayland is not supported.

## Environment this was built and tested on

- Linux (Parrot), Python 3.13, Node 24
- PostgreSQL 17 in a container on `127.0.0.1:55433`; the host's own cluster
  fails to start, which the container sidesteps
- Redis 8 on the host
- Google Chrome drives the browser suites through Playwright
- `./scripts/dev_up.sh` starts whatever is not already running

## How to revert

```bash
git checkout native-capture-modules   # before the join flow and P6
git checkout p4-tools                 # before the privacy blank
git checkout p3-cross-platform        # before the tools
git checkout p1-foundation            # before the Appendix A console
git checkout p0-docs                  # before any code
```

Database migrations roll back with
`cd relay && ../.venv/bin/python -m alembic downgrade <revision>`.

## Change log

- **Built for people who cannot use a terminal.** The agent used to need a
  command line. Now double-clicking it (no arguments) opens a small window that
  asks for the code, checks it with the server and explains a bad one in plain
  words, then shows the consent dialog. The server address is built into the
  agent at build time (`RMM_DEFAULT_RELAY`, set in CI). The Windows installer is
  per-user (no admin rights), has no pages to click through, and opens the agent
  by itself when done. The relay serves it as `rmm-agent-setup-<CODE>.exe`, and
  the installer reads that name to get the code, so the person downloads,
  installs and is asked for consent with nothing to type. Not yet run on a
  real Windows machine.

- **Session expiry, Linux package, reconnect test.** Codes expire after
  `SESSION_CODE_TTL_MINUTES` (60); all three redemption paths share one rule and
  an expired code looks identical to an unknown one. Expiry governs joining, not
  staying, so a live session is never cut off. `.deb` installer added to CI.
  Reconnect test passes 9/9 (relay killed under a running agent; it reconnects unaided).

- **P6 security review.** `docs/SECURITY_REVIEW.md`. Two high findings fixed:
  nothing was rate limited on any route reachable without a credential, and the
  JWT secret defaulted to a placeholder that would have let anyone mint operator
  tokens. Open findings are recorded there rather than dropped.

- **P6 infrastructure.** GitHub Actions for tests and per-OS agent builds, with
  signing steps that activate when certificates are present. Redis pub/sub so a
  session's two halves can live on different relay instances. TLS front end and
  compose overlay. Persistent rotating relay log, separate from the audit trail.

- **Section 4 join flow and section 10 changed-region streaming.** The console
  had been printing a join link that led nowhere; there is now a guest landing
  page and the relay serves the built connectors. Only whole frames were being
  sent; the endpoint now sends the tiles that changed, 97% less bandwidth.

- **Native capture modules.** C on Linux, Rust on Windows, Swift on macOS, as
  sections 5 and 6 require. The agent had been using mss everywhere.

- **P5 privacy blank.** Capture-exclusion on Windows and macOS, guest-lock on
  Linux. The agent reports which it can deliver and the console says so.

- **P3 cross-platform core.** Per-OS setup, and input mapped through the
  display's logical geometry so Retina and DPI-scaled displays land correctly.

- **P4 tools.** Terminal, file transfer, clipboard, on both sides.

- **P2 endpoint agent.** Consent gate enforced by the relay, not only the agent.

- **P1 foundation.** Relay, auth, session model, append-only audit log, console.
