#!/usr/bin/env bash
# Create a support session and print everything the endpoint needs.
#
#   ./scripts/new_session.sh
#
# Override with EMAIL, PASSWORD or RELAY if they differ from the defaults.
set -euo pipefail

RELAY="${RELAY:-http://127.0.0.1:8000}"
EMAIL="${EMAIL:-admin@example.com}"
PASSWORD="${PASSWORD:-ChangeMe123!}"

LAN_IP="$(ip route get 8.8.8.8 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1)"
LAN_IP="${LAN_IP:-127.0.0.1}"

token="$(curl -fsS -X POST "$RELAY/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')"

code="$(curl -fsS -X POST "$RELAY/sessions" \
  -H "Authorization: Bearer $token" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"attended"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])')"

cat <<TEXT

  Session code:  $code

  Console:       http://$LAN_IP:5173
  Relay:         ws://$LAN_IP:8000

  On the endpoint machine:

    Windows   py -m rmm_agent join --relay ws://$LAN_IP:8000 --code $code --verbose
    macOS     python3 -m rmm_agent join --relay ws://$LAN_IP:8000 --code $code --verbose
    Linux     python3 -m rmm_agent join --relay ws://$LAN_IP:8000 --code $code --verbose

  The endpoint will ask its user to allow the session before anything is shared.

TEXT
