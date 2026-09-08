#!/usr/bin/env bash
# Start an endpoint agent for automated testing, with the safety flags that a
# test run must never be without.
#
#   ./scripts/test_agent.sh <CODE> [extra args...]
#
# Always applied, and not negotiable:
#   --blank-no-input-block  a test must never take the keyboard and mouse of
#                           the machine it is running on
#   --blank-watchdog 15     any blank releases itself quickly
#   --no-input              operator input is logged, not injected
#   --auto-consent          no dialog to click
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CODE="${1:?usage: test_agent.sh <CODE> [extra args...]}"
shift || true

LOG="${RMM_AGENT_LOG:-/tmp/rmm-dev-logs/test-agent.log}"
mkdir -p "$(dirname "$LOG")"

cd "$ROOT/agent"
setsid "$ROOT/.venv/bin/python" -m rmm_agent join \
    --relay "${RMM_RELAY:-ws://127.0.0.1:8000}" \
    --code "$CODE" \
    --no-tray \
    --no-input \
    --auto-consent \
    --blank-no-input-block \
    --blank-watchdog 15 \
    "$@" > "$LOG" 2>&1 < /dev/null &

for _ in $(seq 1 30); do
    sleep 0.5
    grep -q "consent granted" "$LOG" 2>/dev/null && break
done

echo "agent joined $CODE (log: $LOG)"
