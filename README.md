# Remote Desktop & Support Platform

Self-hosted remote desktop and remote-support platform: an operator works from a
browser console, through a relay server, to an agent on the endpoint machine.
Built phase by phase against `Remote_Desktop_Platform_Specification.docx`.

| Phase | Scope | Status |
| --- | --- | --- |
| P1 | Relay, auth, session model, audit log, console shell | **Done — checkpoint passing** |
| — | Operator console rebuilt to Appendix A, plus the session transport | **Done — 32/32 conformance checks** |
| P2 | Core session on Windows: capture, control, tray/consent | Code complete, verified on Linux — **Windows checkpoint open** |
| P3 | Cross-platform core: macOS and Linux | **Linux done — 10/10 real capture and input checks**; macOS not started |
| P4 | Tools: file transfer, terminal, clipboard, multi-monitor, screenshot/zoom/annotate | **Done — 13/13 tool checks, 9/9 through the console** |
| P5 | Privacy blank screen | Not started |
| P6 | Hardening, signed installers, deployment | Not started |

Read `PROJECT_STATUS.md` for what actually works right now.

## Layout

```
relay/      FastAPI relay server (auth, sessions, audit, session transport)
console/    React + TypeScript + Vite + Tailwind operator console (Appendix A)
agent/      endpoint agent: consent, tray, capture, input, enrolment
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

Create a session in the console, copy its code, then join with the agent:

```bash
cd agent
python -m pip install -r requirements.txt

python -m rmm_agent status                       # what this machine supports
python -m rmm_agent join --code <CODE>           # real screen, tray, consent
python -m rmm_agent join --code <CODE> --synthetic --no-tray   # no display needed
```

The agent asks the person at the keyboard to allow the session. **Nothing is
captured before they do** — and the relay enforces that too, dropping any frame
that arrives before a decision is recorded.

Once allowed, the connection indicator turns green, the waiting line flips to
"Your guest has joined.", a LIVE preview appears, and Join opens the full viewer.

To test from another machine, bind the relay to the network
(`uvicorn app.main:app --host 0.0.0.0 --port 8000`) and point the agent at it
with `--relay ws://<relay-host>:8000`.

## Tests

```bash
cd relay && ../.venv/bin/python -m pytest        # 33 API and database tests

# Phase 2 session flow: the consent gate and device authentication
.venv/bin/python tests/e2e/p2_session_flow.py    # relay must be running

# Phase 3 Linux endpoint: real capture, real input injection
.venv/bin/python tests/e2e/p3_linux_endpoint.py

# Phase 4 tools: terminal, file transfer, clipboard
.venv/bin/python tests/e2e/p4_tools.py           # relay must be running
.venv/bin/python tests/e2e/p4_console_tools.py docs/screenshots   # + console

# Appendix A conformance - needs the relay, the console and the agent running
GUEST_CODE=<CODE> GUEST_LOG=/path/to/agent.log \
  .venv/bin/python tests/e2e/console_appendix_a.py docs/screenshots
```

The browser suite drives the real console in Google Chrome against the real
agent and checks Appendix A point by point, including that pointer input lands
on the right guest coordinate when the canvas is letterboxed.

## Finishing Phase 2

Phase 2's checkpoint requires a real Windows machine. Work through
`docs/PHASE2_WINDOWS_CHECKLIST.md` there; `docs/PHASE2_STATUS.md` records
exactly what is and is not proven.
