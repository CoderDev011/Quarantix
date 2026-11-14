#!/usr/bin/env bash
# End-to-end smoke test of the control plane on a real uvicorn server (F13).
# Checks what in-process tests cannot: the live SSE feed over real HTTP.
# Uses random throwaway tokens and a temp database. Exits non-zero on any failure.
# Usage (inside WSL, repo root): bash scripts/smoke_api.sh
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."

PORT="${SMOKE_PORT:-8765}"
BASE="http://127.0.0.1:$PORT"
WORK="$(mktemp -d)"
ADMIN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
KEY="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
export AGENTWALL_ADMIN_TOKEN="$ADMIN"
export AGENTWALL_AGENT_KEYS="smoke-agent:$KEY"
export AGENTWALL_DB="sqlite+aiosqlite:///$WORK/smoke.db"

uv run uvicorn --factory quarantix.api.app:app_from_env --host 127.0.0.1 --port "$PORT" \
  --workers 1 --log-level warning > "$WORK/server.log" 2>&1 &
SERVER=$!
cleanup() { kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

fail() { echo "FAIL: $1"; echo "--- server log:"; cat "$WORK/server.log"; exit 1; }
pass() { echo "ok    $1"; }

for _ in $(seq 1 50); do curl -fsS "$BASE/healthz" > /dev/null 2>&1 && break; sleep 0.2; done
curl -fsS "$BASE/healthz" > /dev/null || fail "server did not become healthy"
pass "server healthy"

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
