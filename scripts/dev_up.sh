#!/usr/bin/env bash
# Bring up everything the test suites need, and only what is not already up.
#
#   ./scripts/dev_up.sh          # start what is missing
#   ./scripts/dev_up.sh --status # report without starting anything
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="${RMM_LOG_DIR:-/tmp/rmm-dev-logs}"
mkdir -p "$LOGS"

alive() { curl -fsS -m 3 -o /dev/null "$1" 2>/dev/null; }

report() {
    printf '%-10s %s\n' "$1" "$2"
}

status() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^rdp-postgres$' \
        && report postgres up || report postgres DOWN
    redis-cli ping >/dev/null 2>&1 && report redis up || report redis DOWN
    alive http://127.0.0.1:8000/health && report relay up || report relay DOWN
    alive http://localhost:5173/ && report console up || report console DOWN
}

if [[ "${1:-}" == "--status" ]]; then
    status
    exit 0
fi

# PostgreSQL - a container, because the host's own cluster fails to start.
if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^rdp-postgres$'; then
    echo "starting postgres..."
    docker start rdp-postgres >/dev/null 2>&1 || docker run -d --name rdp-postgres \
        -e POSTGRES_USER=rdp -e POSTGRES_PASSWORD=rdp_dev_pass -e POSTGRES_DB=rdp \
        -p 55433:5432 docker.io/library/postgres:17-alpine >/dev/null
    for _ in $(seq 1 30); do
        docker exec rdp-postgres pg_isready -U rdp >/dev/null 2>&1 && break
        sleep 1
    done
fi

if ! redis-cli ping >/dev/null 2>&1; then
    echo "redis is not running: sudo systemctl start redis-server" >&2
fi

# Relay. setsid so it outlives the shell that started it.
if ! alive http://127.0.0.1:8000/health; then
    echo "starting relay..."
    (cd "$ROOT/relay" && setsid "$ROOT/.venv/bin/python" -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8000 > "$LOGS/relay.log" 2>&1 < /dev/null &)
    for _ in $(seq 1 30); do
        alive http://127.0.0.1:8000/health && break
        sleep 1
    done
fi

# Console.
if ! alive http://localhost:5173/; then
    echo "starting console..."
    (cd "$ROOT/console" && setsid npm run dev > "$LOGS/console.log" 2>&1 < /dev/null &)
    for _ in $(seq 1 40); do
        alive http://localhost:5173/ && break
        sleep 1
    done
fi

status
echo
echo "logs in $LOGS"
