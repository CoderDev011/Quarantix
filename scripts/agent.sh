#!/usr/bin/env bash
# Run the guarded agent with its settings loaded from .env (no manual exports needed).
#   bash scripts/agent.sh devops                         # a normal day
#   bash scripts/agent.sh devops --plant "<text>"        # with a planted record
#   bash scripts/agent.sh support
# Reads .env, picks the domain's agent key from AGENTWALL_AGENT_KEYS, never prints a secret.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

DOMAIN="${1:-}"
case "$DOMAIN" in
  devops | support) ;;
  *) echo "usage: bash scripts/agent.sh devops|support [--plant \"<text>\"]"; exit 2 ;;
esac

[[ -f .env ]] || { echo "No .env file: run 'cp .env.example .env' and fill it in."; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a

AGENT="$DOMAIN-agent"
KEY="$(printf '%s' "${AGENTWALL_AGENT_KEYS:-}" | tr ',' '\n' | sed -n "s/^ *$AGENT:\(.*\)$/\1/p" | head -1)"
if [[ -z "$KEY" ]]; then
  echo "No key for $AGENT in AGENTWALL_AGENT_KEYS in .env (expected '$AGENT:<key>')."
  exit 1
fi
if [[ -z "${GEMINI_API_KEY:-}" || "${GEMINI_API_KEY}" == *replace-me* ]]; then
  echo "GEMINI_API_KEY is not set in .env, so the agent has no model to run."
  exit 1
fi
export QX_AGENT_KEY="$KEY"
export QX_API="${QX_API:-http://127.0.0.1:8000}"

if ! curl -s -m 5 "$QX_API/healthz" >/dev/null; then
  echo "Note: the control plane at $QX_API is not reachable; the SDK will decide offline (fail-safe)."
fi

exec uv run python scripts/guarded_agent.py "$@"
