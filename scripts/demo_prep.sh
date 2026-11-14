#!/usr/bin/env bash
# Get the demo stack ready in one command (inside WSL, repo root). Never prints a secret.
#   bash scripts/demo_prep.sh            # sync tunnel URL, enforce all agents, booth reset, checks
#   bash scripts/demo_prep.sh --rebuild  # also rebuild and restart the Docker stack first
# Exit code 0 only when every required check passed.
set -uo pipefail
cd "$(dirname "$0")/.."
API=http://localhost:8000
FAILED=0
ok()   { printf '  ok    %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAILED=1; }

[[ -f .env ]] || { echo "no .env: cp .env.example .env and fill it in"; exit 1; }
TOKEN="$(grep -E '^AGENTWALL_ADMIN_TOKEN=' .env | tail -1 | cut -d= -f2-)"
[[ -n "$TOKEN" && "$TOKEN" != *replace-me* ]] || { echo "AGENTWALL_ADMIN_TOKEN is not set in .env"; exit 1; }
auth=(-H "Authorization: Bearer $TOKEN")

echo "Tunnel"
TUNNEL=""
for port in 20241 20242 20243 20244 20245; do
  host="$(curl -s -m 2 "http://127.0.0.1:$port/quicktunnel" 2>/dev/null | sed -n 's/.*"hostname":"\([^"]*\)".*/\1/p')"
  if [[ -n "$host" ]]; then TUNNEL="https://$host"; break; fi
done
CHANGED=0
if [[ -n "$TUNNEL" ]]; then
  ok "cloudflared is running: $TUNNEL"
  current="$(grep -E '^PUBLIC_BASE_URL=' .env | tail -1 | cut -d= -f2-)"
  if [[ "$current" != "$TUNNEL" ]]; then
    if grep -qE '^PUBLIC_BASE_URL=' .env; then
      sed -i "s#^PUBLIC_BASE_URL=.*#PUBLIC_BASE_URL=$TUNNEL#" .env
    else
      echo "PUBLIC_BASE_URL=$TUNNEL" >> .env
    fi
    ok "PUBLIC_BASE_URL updated in .env (was: ${current:-unset})"
    CHANGED=1
  else
    ok "PUBLIC_BASE_URL already matches the tunnel"
  fi
else
  warn "no cloudflared quick tunnel found: start one with 'cloudflared tunnel --url http://localhost:8000'"
fi

echo "Stack"
if [[ "${1:-}" == "--rebuild" ]]; then
  if docker compose up -d --build >/tmp/qx-demo-build.log 2>&1; then ok "rebuilt and started"
  else bad "docker compose up --build failed (last lines below; full log /tmp/qx-demo-build.log)"; tail -8 /tmp/qx-demo-build.log; fi
elif [[ $CHANGED == 1 ]]; then
  docker compose up -d --force-recreate api >/dev/null 2>&1 && ok "api restarted with the new URL" || bad "api restart failed"
fi
for _ in $(seq 1 30); do curl -s -m 2 "$API/healthz" >/dev/null && break; sleep 1; done
curl -s -m 5 "$API/healthz" >/dev/null && ok "API healthy" || bad "API not reachable on $API"
curl -s -m 5 http://localhost:9000/_log >/dev/null && ok "attacker page up (http://localhost:9000)" || bad "attacker page not reachable"

echo "Agents"
agents="$(curl -s -m 5 "${auth[@]}" "$API/v1/agents" | python3 -c 'import json,sys; print(" ".join(a["name"] for a in json.load(sys.stdin)["agents"]))' 2>/dev/null)"
[[ -n "$agents" ]] || bad "could not list agents (is the admin token right?)"
for agent in $agents; do
  mode="$(curl -s -m 5 -X PUT "${auth[@]}" -H 'Content-Type: application/json' -d '{"mode":"enforce"}' \
    "$API/v1/agents/$agent/mode" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("mode",""))' 2>/dev/null)"
  [[ "$mode" == "enforce" ]] && ok "$agent: enforce" || bad "$agent: could not set enforce"
done

echo "Reset"
reset="$(curl -s -m 15 -X POST "${auth[@]}" -H 'Content-Type: application/json' -d '{}' "$API/v1/arena/admin/reset")"
echo "$reset" | grep -q '"restored"' && ok "booth reset: day-one policies restored, Autopilot rules removed" || bad "booth reset failed"
curl -s -m 5 -X POST http://localhost:9000/_reset >/dev/null && ok "attacker page cleared" || warn "could not clear the attacker page"

echo "Arena"
stats="$(curl -s -m 5 "$API/v1/arena/stats")"
echo "$stats" | python3 -c 'import json,sys; s=json.load(sys.stdin); print("  ok    QR code points to:", (s.get("public_url") or "(not set: localhost only)").rstrip("/") + "/arena"); print("  ok    baseline model:", s.get("baseline_model"), "| economy:", s.get("economy"))' 2>/dev/null \
  || bad "arena stats unavailable"
if [[ -n "$TUNNEL" ]]; then
  code="$(curl -s -m 15 -o /dev/null -w '%{http_code}' "$TUNNEL/arena/screen")"
  [[ "$code" == 200 ]] && ok "big screen reachable through the tunnel" || bad "tunnel answered $code for /arena/screen"
fi

echo
if [[ $FAILED == 0 ]]; then
  echo "READY."
  echo "  Projector:       ${TUNNEL:-$API}/arena/screen"
  echo "  Console:         ${TUNNEL:-$API}/"
  echo "  Attack station:  ${TUNNEL:-$API}/docs  -> POST /v1/arena/attempts"
  echo "  Attacker page:   http://localhost:9000"
else
  echo "NOT READY: fix the FAIL lines above."
fi
exit $FAILED
