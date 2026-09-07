# Remote Desktop & Support Platform

Self-hosted remote desktop and remote-support platform: an operator works from a
browser console, through a relay server, to an agent on the endpoint machine.
Built phase by phase against `Remote_Desktop_Platform_Specification.docx`.

| Phase | Scope | Status |
| --- | --- | --- |
| P1 | Relay, auth, session model, audit log, console shell | **Done — checkpoint passing** |
| P2 | Core session on Windows: capture, control, tray/consent | Not started |
| P3 | Same on macOS and Linux | Not started |
| P4 | File transfer, terminal, clipboard, multi-monitor, screenshot/zoom/annotate | Not started |
| P5 | Privacy blank screen | Not started |
| P6 | Hardening, signed installers, deployment | Not started |

Read `PROJECT_STATUS.md` for what actually works right now.

## Layout

```
relay/      FastAPI relay server (auth, sessions, audit) + Alembic migrations
console/    React + TypeScript + Vite + Tailwind operator console
agent/      Endpoint agent - Phase 2
infra/      docker-compose stack and the nginx config
tests/e2e/  Browser acceptance tests, one per phase checkpoint
docs/       Screenshots from the passing phase checkpoints
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

## Tests

```bash
cd relay && ../.venv/bin/python -m pytest              # 22 API/database tests
.venv/bin/python tests/e2e/p1_console.py docs/screenshots   # 10 browser checks
```

The browser test drives the real console in Google Chrome and is the Phase 1
checkpoint from the specification: an operator logs in, a session record is
created and appears in the console, and the audit log records it.
