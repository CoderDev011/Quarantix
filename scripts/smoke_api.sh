#!/usr/bin/env bash
# End-to-end smoke test of the control plane over real HTTP (F13, F23).
# Checks what in-process tests cannot: the live SSE feed, cookie login, the served console.
# Uses random throwaway tokens and a temp database. Exits non-zero on any failure.
# Usage (inside WSL, repo root):
#   bash scripts/smoke_api.sh                          # local uvicorn from the source tree
#   SMOKE_IMAGE=quarantix:demo bash scripts/smoke_api.sh  # the built Docker image
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."

PORT="${SMOKE_PORT:-8765}"
BASE="http://127.0.0.1:$PORT"
WORK="$(mktemp -d)"
ADMIN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
KEY="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
IMAGE="${SMOKE_IMAGE:-}"
CONTAINER="quarantix-smoke-$$"

# Never test someone else's server by accident: the port must be free before we start ours.
if curl -s --max-time 1 -o /dev/null "$BASE/healthz"; then
  echo "FAIL: port $PORT is already in use; stop that server or set SMOKE_PORT"
  rm -rf "$WORK"
  exit 1
fi

if [[ -n "$IMAGE" ]]; then
  docker run -d --rm --name "$CONTAINER" -p "127.0.0.1:$PORT:8000" \
    -e AGENTWALL_ADMIN_TOKEN="$ADMIN" -e AGENTWALL_AGENT_KEYS="smoke-agent:$KEY" \
    "$IMAGE" > /dev/null
  cleanup() { docker logs "$CONTAINER" > "$WORK/server.log" 2>&1 || true; docker stop "$CONTAINER" > /dev/null 2>&1 || true; rm -rf "$WORK"; }
  server_log() { docker logs "$CONTAINER" 2>&1 | tail -40; }
else
  export AGENTWALL_ADMIN_TOKEN="$ADMIN"
  export AGENTWALL_AGENT_KEYS="smoke-agent:$KEY"
  export AGENTWALL_DB="sqlite+aiosqlite:///$WORK/smoke.db"
  uv run uvicorn --factory quarantix.api.app:app_from_env --host 127.0.0.1 --port "$PORT" \
    --workers 1 --log-level warning > "$WORK/server.log" 2>&1 &
  SERVER=$!
  cleanup() { kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true; rm -rf "$WORK"; }
  server_log() { cat "$WORK/server.log"; }
fi
trap cleanup EXIT

fail() { echo "FAIL: $1"; echo "--- server log:"; server_log; exit 1; }
pass() { echo "ok    $1"; }

for _ in $(seq 1 100); do curl -fsS "$BASE/healthz" > /dev/null 2>&1 && break; sleep 0.2; done
curl -fsS "$BASE/healthz" > /dev/null || fail "server did not become healthy"
pass "server healthy${IMAGE:+ (image $IMAGE)}"

if [[ -n "$IMAGE" ]]; then
  PAGE="$(curl -fsS "$BASE/")" || fail "console page not served"
  [[ "$PAGE" == *'<div id="root">'* ]] || fail "/ did not return the console"
  pass "console served from the image"
  COOKIES="$WORK/cookies.txt"
  CODE="$(curl -sS -c "$COOKIES" -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' \
    -d "{\"token\":\"$ADMIN\"}" "$BASE/v1/session")"
  [[ "$CODE" == "200" ]] || fail "console login returned $CODE"
  CODE="$(curl -sS -b "$COOKIES" -o /dev/null -w '%{http_code}' "$BASE/v1/agents")"
  [[ "$CODE" == "200" ]] || fail "the login cookie did not authorize /v1/agents ($CODE)"
  pass "console login cookie works"
fi

PACK=$'schema_version: 1\npack: smoke\nrules: []\n'
curl -fsS -X PUT "$BASE/v1/policies/packs/smoke" -H "Authorization: Bearer $ADMIN" \
  --data-binary "$PACK" > /dev/null || fail "saving a policy pack"
pass "policy pack saved"

EVENT='{"events":[{"schema_version":1,"event_id":"smoke-1","run_id":"run-1","agent":"smoke-agent","mode":"guard","kind":"tool.call","time":"2026-11-14T12:00:00+00:00","tool":"pay"}]}'
RESULT="$(curl -fsS -X POST "$BASE/v1/events:batch" -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' --data "$EVENT")" || fail "uploading an event"
[[ "$RESULT" == *'"accepted":1'* ]] || fail "event not accepted: $RESULT"
pass "event uploaded"

# The live feed: read for up to 3 seconds and expect the event with SSE id 1.
STREAM="$(curl -sS -N --max-time 3 "$BASE/v1/events/stream?token=$ADMIN" 2>/dev/null || true)"  # the stream never ends: cut it off
[[ "$STREAM" == *"id: 1"* && "$STREAM" == *'"event_id":"smoke-1"'* ]] || fail "SSE stream did not deliver the event"
pass "SSE stream delivered the event"

STREAM_AFTER="$(curl -sS -N --max-time 2 -H 'Last-Event-ID: 1' "$BASE/v1/events/stream?token=$ADMIN" 2>/dev/null || true)"
[[ "$STREAM_AFTER" != *'"event_id":"smoke-1"'* ]] || fail "Last-Event-ID resume sent a duplicate"
pass "Last-Event-ID resume skips what was already seen"

ETAG="$(curl -fsS -D - -o /dev/null "$BASE/v1/policies/bundle?agent=smoke-agent&wait=0" \
  -H "Authorization: Bearer $KEY" | tr -d '\r' | awk -F': ' 'tolower($1)=="etag"{print $2}')"
[[ -n "$ETAG" ]] || fail "bundle has no ETag"
CODE="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/v1/policies/bundle?agent=smoke-agent&wait=0" \
  -H "Authorization: Bearer $KEY" -H "If-None-Match: $ETAG")"
[[ "$CODE" == "304" ]] || fail "unchanged bundle returned $CODE, expected 304"
pass "bundle sync: ETag + 304 when unchanged"

CODE="$(curl -sS -o /dev/null -w '%{http_code}' "$BASE/v1/events/stream")"
[[ "$CODE" == "401" ]] || fail "stream without a token returned $CODE, expected 401"
pass "stream refuses requests without the admin token"

echo "All smoke checks passed."
