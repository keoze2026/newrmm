# Deploying the relay and console

Endpoints on other machines — the Windows and macOS boxes — need a relay they
can reach. Anything that resolves and accepts traffic will do: a VPS, a machine
on the same LAN, or a tunnel.

## What runs where

```
  operator's browser  ─────►  nginx :80/:443  ─────►  relay :8000
                                    │                    │
                                    │                    ├── postgres
                                    │                    └── redis
  endpoint agent  ────────────────►─┘
```

Both the console and the agents talk to the **same** host. The console uses
`/api`; agents use `ws://<host>/api/ws/guest/<CODE>`.

## The stack

```bash
cd infra
JWT_SECRET="$(openssl rand -hex 32)" \
POSTGRES_PASSWORD="$(openssl rand -hex 16)" \
CONSOLE_PORT=80 \
docker compose up -d --build
```

Then create the first operator:

```bash
docker compose exec relay python seed.py \
  --email you@example.com --password 'a-real-password'
```

Console at `http://<host>/`, sign in, **Create +**, and give the endpoint:

```
--relay ws://<host>/api
```

## Before it faces the internet

The compose stack is plain HTTP. That is fine on a trusted LAN and **not** fine
on a public address — sessions carry screen contents and keystrokes.

- **TLS.** Put a certificate on nginx (or a proxy in front of it) and use
  `wss://<host>/api` for agents. The spec requires encrypted transport; this is
  the one item that must not be skipped.
- **`JWT_SECRET`.** Set it to a real random value. The default is a placeholder
  and anyone holding it can mint operator tokens.
- **Postgres password.** Same.
- **`CORS_ORIGINS`.** Set it to the console's real origin.
- **One relay process.** The session hub is in-memory, so sessions do not span
  instances. Do not scale `relay` past one replica until the Redis pub/sub
  fan-out lands in Phase 6.

## Reaching it without a server

For a quick test from another machine on the same network, run the relay on
`0.0.0.0` and point the agent at the LAN address:

```bash
cd relay && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
cd console && npm run dev            # already binds every interface
```

```bash
./scripts/new_session.sh             # prints the address and the join command
```

Open port 8000 (and 5173 for the console) if a firewall is running:

```bash
sudo ufw allow 8000/tcp && sudo ufw allow 5173/tcp
```

## Health

```bash
curl http://<host>/api/health
```

`{"status":"ok","checks":{"database":"ok","redis":"ok"}}` means the relay,
Postgres and Redis are all up. `degraded` names the one that is not.
