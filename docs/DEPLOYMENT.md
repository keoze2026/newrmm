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

## TLS

Section 9 requires all traffic encrypted, and a session carries screen contents
and keystrokes, so this is the one item that must not be skipped on a public
address.

Get a certificate for your domain:

```bash
sudo certbot certonly --standalone -d relay.example.com
sudo mkdir -p infra/certs
sudo cp /etc/letsencrypt/live/relay.example.com/fullchain.pem infra/certs/
sudo cp /etc/letsencrypt/live/relay.example.com/privkey.pem  infra/certs/
```

Then bring the stack up with the TLS overlay:

```bash
cd infra
JWT_SECRET="$(openssl rand -hex 32)" \
POSTGRES_PASSWORD="$(openssl rand -hex 16)" \
CORS_ORIGINS="https://relay.example.com" \
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build
```

That redirects port 80 to 443, serves TLS 1.2 and 1.3 only, and sets HSTS.
Agents then connect with `wss://`:

```bash
python -m rmm_agent join --relay wss://relay.example.com/api --code ABCD1234
```

Renewal writes to `infra/certbot-webroot`, which nginx serves at
`/.well-known/acme-challenge/`; copy the renewed files into `infra/certs` and
reload nginx.

## Before it faces the internet

Beyond TLS:
- **`JWT_SECRET`.** Set it to a real random value. The default is a placeholder
  and anyone holding it can mint operator tokens.
- **Postgres password.** Same.
- **`CORS_ORIGINS`.** Set it to the console's real origin.
- **Scaling.** Sessions are relayed through Redis pub/sub when the two halves
  land on different instances, so `relay` can run more than one replica. Every
  instance must share the same Redis and the same database. Without Redis a
  single instance still works: the local path is tried first and Redis is only
  consulted when the peer is elsewhere.

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
