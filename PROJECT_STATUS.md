# Project status

Updated after every change. Read this before claiming anything works.

## Where the build is

Phase 1 (Foundation) is complete. On top of it, the operator console has been
rebuilt to **Appendix A** of the specification, and the session transport that
Appendix A depends on is working: a guest can join a session, stream its screen,
and be controlled from the console viewer.

The Phase 2 endpoint agent does **not** exist. What connects today is
`agent/dev_guest.py`, a development guest that has only ever run on Linux.

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

Last run: **31/31 pytest tests passed**, **32/32 Appendix A browser checks
passed** against a live relay, PostgreSQL 17, Redis 8 and a connected guest.
Screenshots in `docs/screenshots/`.

## What does NOT work yet

- **No production endpoint agent.** `agent/dev_guest.py` is a development guest.
  It has no installer, no tray, no consent surface and no unattended enrolment,
  and it has only ever been run on Linux.
- **Only Linux has been exercised.** No claim is made about Windows or macOS —
  no code has run there. The console is one web app, so it is expected to behave
  identically, but that is untested until Phase 3.
- Terminal, Files, Download and Send/Get file are wired into the UI but have no
  implementation behind them; they say so on screen. They are Phase 4.
- Chat, Tools and Locate are placeholders, labelled as such.
- Privacy blank sends the message and the guest logs it, but no guest actually
  blanks a screen yet. That is Phase 5.
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
git checkout p1-foundation      # before the Appendix A console
git checkout p0-docs            # before any code
```

To undo a database migration:

```bash
cd relay && ../.venv/bin/python -m alembic downgrade 0001_initial
```

## Change log

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
