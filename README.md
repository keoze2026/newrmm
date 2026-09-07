# Remote Desktop & Support Platform

Self-hosted remote desktop and remote-support platform: an operator works from a
browser console, through a relay server, to an agent on the endpoint machine.
Built phase by phase against `Remote_Desktop_Platform_Specification.docx`.

| Phase | Scope | Status |
| --- | --- | --- |
| P1 | Relay, auth, session model, audit log, console shell | **Done — checkpoint passing** |
| — | Operator console rebuilt to Appendix A, plus the session transport | **Done — 32/32 conformance checks** |
| P2 | Core session on Windows: capture, control, tray/consent | Not started |
| P3 | Same on macOS and Linux | Not started |
| P4 | File transfer, terminal, clipboard, multi-monitor, screenshot/zoom/annotate | Not started |
| P5 | Privacy blank screen | Not started |
| P6 | Hardening, signed installers, deployment | Not started |

Read `PROJECT_STATUS.md` for what actually works right now.

## Layout

```
relay/      FastAPI relay server (auth, sessions, audit, session transport)
console/    React + TypeScript + Vite + Tailwind operator console (Appendix A)
agent/      dev_guest.py development guest; the real agent is Phase 2
infra/      docker-compose stack and the nginx config
tests/e2e/  Browser conformance tests
docs/       Screenshots from the passing runs
```

## Run it locally

Start PostgreSQL and Redis (a container is fine):

```bash
docker run -d --name rdp-postgres -p 55433:5432 \
  -e POSTGRES_USER=rdp -e POSTGRES_PASSWORD=rdp_dev_pass -e POSTGRES_DB=rdp \
  postgres:17-alpine
docker run -d --name rdp-redis -p 6379:6379 redis:7-alpine
```

Relay:

```bash
python3 -m venv .venv
.venv/bin/pip install -r relay/requirements-dev.txt
cd relay && ../.venv/bin/python -m alembic upgrade head
../.venv/bin/python seed.py --email admin@example.com --password 'ChangeMe123!'
../.venv/bin/python -m uvicorn app.main:app --port 8000
```

Console:

```bash
cd console && npm install && npm run dev     # http://localhost:5173
```

Sign in with the seeded account. The console proxies `/api` to the relay.

## See a live session

Create a session in the console, copy its code, then join as a guest:

```bash
# Streams a generated test image - no display needed
.venv/bin/python agent/dev_guest.py --code <CODE> --synthetic

# Or stream this machine's real screen
.venv/bin/python agent/dev_guest.py --code <CODE>
```

The connection indicator turns green, the waiting line flips to "Your guest has
joined.", a LIVE preview appears, and Join opens the full viewer.

## Tests

```bash
cd relay && ../.venv/bin/python -m pytest        # 31 API and database tests

# Appendix A conformance - needs the relay, the console and a guest running
GUEST_CODE=<CODE> GUEST_LOG=/tmp/guest.log \
  .venv/bin/python tests/e2e/console_appendix_a.py docs/screenshots
```

The browser suite drives the real console in Google Chrome against a live guest
and checks Appendix A point by point, including that pointer input lands on the
right guest coordinate when the canvas is letterboxed.
