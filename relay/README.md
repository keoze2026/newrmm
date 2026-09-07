# Relay server

FastAPI service holding operator auth, the session model and the append-only
audit log. Phase 1 scope; the WebSocket session transport arrives in Phase 2.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env          # then edit DATABASE_URL / JWT_SECRET
alembic upgrade head
python seed.py --email you@example.com --password 'YourPassword1!'
uvicorn app.main:app --reload
```

Interactive API docs: <http://127.0.0.1:8000/docs>

## Tests

```bash
python -m pytest            # expects an empty database named rdp_test
```

## Routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness plus database and Redis checks |
| POST | `/auth/login` | Exchange credentials for a JWT |
| GET | `/auth/me` | The authenticated operator |
| POST | `/sessions` | Create an attended or unattended session |
| GET | `/sessions` | List sessions |
| GET | `/sessions/{id}` | One session |
| PATCH | `/sessions/{id}` | Move a session to `active` or `ended` |
| POST | `/devices` | Enroll a device; returns the secret once |
| GET | `/devices` | List enrolled devices |
| GET | `/audit` | Read the audit trail (no write routes exist) |
