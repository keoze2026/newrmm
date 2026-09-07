# Project status

Updated after every change. Read this before claiming anything works.

## Where the build is

Phase 1 (Foundation) is complete and its specification checkpoint passes.
Nothing from Phase 2 onward exists yet — there is no endpoint agent, no screen
capture, no remote control, and no session transport.

## What works, and how it was verified

| Capability | Verified by |
| --- | --- |
| Operator login with Argon2 password hashing, JWT bearer tokens | `relay/tests/test_auth.py`, browser test step 3 |
| Wrong password and unknown account rejected, and audited | `relay/tests/test_auth.py`, browser test step 2 |
| Every protected route rejects anonymous and forged tokens | `relay/tests/test_auth.py` |
| Attended session creation with a unique 8-character code | `relay/tests/test_sessions.py`, browser test step 5 |
| Unattended session bound to an enrolled device | `relay/tests/test_sessions.py` |
| Session state transitions `pending → active → ended` with timestamps | `relay/tests/test_sessions.py`, browser test step 7 |
| Sessions persist and list in the console across reloads | Browser test step 6 |
| Device enrollment; the secret is shown once and stored only as an Argon2 hash | `relay/tests/test_devices.py`, browser test step 9 |
| Audit rows for login success/failure, session create, state change, enrollment | `relay/tests/test_audit.py`, browser test step 8 |
| Audit log is append-only — the database rejects UPDATE and DELETE | `relay/tests/test_audit.py::test_audit_log_is_append_only` |
| Health endpoint reports database and Redis | `relay/tests/test_health.py`, browser test step 4 |
| Compose stack builds, migrates on start, and serves the console and API through nginx | Stack brought up and the full browser test re-run against it |

Last run: 22/22 pytest tests passed. The 10 browser checks passed twice — once
against the Vite dev server and the local relay, and again against the deployed
compose stack (nginx serving built assets, relay in a container, its own
PostgreSQL and Redis). Screenshots in `docs/screenshots/`.

Bringing the compose stack up found a real defect that no unit test would have
caught: `email-validator` was installed into the development virtualenv by hand
but missing from `relay/requirements.txt`, so the containerised relay crashed on
startup. Fixed by pinning `pydantic[email]`, then rebuilt and re-verified.

## What does NOT work yet

- No endpoint agent exists. `agent/` is an empty placeholder.
- No screen capture, no input injection, no tray or consent UI, no privacy blank.
- No WebSocket session transport. Redis is connected and health-checked only;
  it carries no pub/sub traffic yet.
- Session state is moved by the operator from the console. Nothing moves it
  automatically, because no endpoint joins a session yet.
- Sessions have no expiry or code rotation.
- TLS is not configured. The compose stack serves plain HTTP on the console
  port; a certificate and an HTTPS listener are Phase 6 work.
- The platform has only been exercised on Linux. No claim is made about Windows
  or macOS — no code has run there.

## Environment this was built and tested on

- Linux (Parrot OS), Python 3.13.5, Node 24.20.0
- PostgreSQL 17 in a container on `127.0.0.1:55433` (the host's system Postgres
  cluster is present but fails to start; the container sidesteps it)
- Redis 8 on the host at `127.0.0.1:6379`
- Google Chrome drives the browser acceptance test through Playwright

## How to revert

Every phase is tagged. To drop back to the state before Phase 1:

```bash
git checkout p0-docs
```

To undo the Phase 1 database schema:

```bash
cd relay && ../.venv/bin/python -m alembic downgrade base
```

## Change log

- **P1 — Foundation.** Relay server (FastAPI, async SQLAlchemy, Alembic), operator
  auth, device enrollment, session model, append-only audit log with a database
  trigger enforcing immutability, health checks, React/TypeScript console shell
  with sessions, devices and audit views, compose stack and nginx config.
  Tagged `p1-foundation`.
