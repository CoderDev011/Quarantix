#!/usr/bin/env bash
# Is this machine ready to run the demo? (F23). Required checks fail the run (exit 1);
# optional ones only warn. Never prints a secret: key values are shown as set/unset only.
# Usage (inside WSL, repo root): bash scripts/doctor.sh [--demo]
#   --demo  also require what only the demo laptop needs (memory for the full stack + Ollama)
set -uo pipefail
cd "$(dirname "$0")/.."
DEMO=0; [[ "${1:-}" == "--demo" ]] && DEMO=1
FAILED=0

ok()   { printf '  ok    %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAILED=1; }
need() { if [[ $DEMO == 1 ]]; then bad "$1"; else warn "$1 (required on the demo laptop)"; fi; }

echo "Tools"
for tool in git uv pnpm docker; do
  if command -v "$tool" >/dev/null 2>&1; then ok "$tool $("$tool" --version 2>&1 | head -1)"; else bad "$tool missing"; fi
done
if docker info >/dev/null 2>&1; then ok "docker daemon running"; else bad "docker daemon not reachable"; fi

echo "Memory"
MEM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
if (( MEM_GB >= 10 )); then ok "${MEM_GB} GB available to WSL"; else need "only ${MEM_GB} GB available to WSL; the full stack + Ollama needs ~10 GB"; fi

echo "Ports"
for port in 8000 9000 11434; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${port}$"; then warn "port $port is already in use"; else ok "port $port free"; fi
done

echo "Settings (.env)"
if [[ -f .env ]]; then
  ok ".env present"
  value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2-; }
  for key in AGENTWALL_ADMIN_TOKEN AGENTWALL_AGENT_KEYS GEMINI_API_KEY; do
    v="$(value "$key")"
    if [[ -z "$v" || "$v" == *replace-me* ]]; then
      if [[ "$key" == GEMINI_API_KEY ]]; then warn "$key not set (replay mode still works)"; else bad "$key not set"; fi
    else ok "$key set (${#v} chars)"; fi
  done
  token="$(value AGENTWALL_ADMIN_TOKEN)"
  if [[ -n "$token" && "$token" != *replace-me* && ${#token} -lt 16 ]]; then
    bad "AGENTWALL_ADMIN_TOKEN is shorter than 16 characters"
  fi
else
  bad ".env missing: cp .env.example .env and fill it in"
fi
if git check-ignore -q .env 2>/dev/null; then ok ".env is git-ignored"; else bad ".env is NOT git-ignored"; fi

echo "Data"
CASSETTES=$(find cassettes -name '*.json' 2>/dev/null | wc -l)
if (( CASSETTES > 0 )); then ok "$CASSETTES recorded LLM responses (offline replay)"; else need "no cassettes recorded yet: the offline demo needs them"; fi
if [[ -f dashboard/dist/index.html ]]; then ok "dashboard built"; else warn "dashboard not built (docker build does it; for local runs: pnpm --dir dashboard build)"; fi

echo "Services"
OLLAMA="${OLLAMA_URL:-http://localhost:11434}"
if curl -fsS --max-time 2 "$OLLAMA/api/tags" >/dev/null 2>&1; then ok "Ollama reachable at $OLLAMA"; else need "Ollama not reachable at $OLLAMA"; fi
API="${QX_API:-http://localhost:8000}"
if curl -fsS --max-time 2 "$API/healthz" >/dev/null 2>&1; then ok "control plane healthy at $API"; else warn "control plane not running at $API (start: docker compose up -d)"; fi

echo
if (( FAILED )); then echo "Not ready: fix the FAIL lines above."; exit 1; fi
echo "Ready."
