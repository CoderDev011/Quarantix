#!/usr/bin/env bash
# Toolchain check for AgentWall development (run inside WSL).
# Exits non-zero if a required tool is missing. See docs/features/F23-packaging-ops.md.
set -uo pipefail

required=(git python3 uv node pnpm docker)
optional=(ollama cloudflared)
missing=0

check() {
  local tool="$1" kind="$2"
  if command -v "$tool" >/dev/null 2>&1; then
    printf '%-12s %-9s %s\n' "$tool" "ok" "$("$tool" --version 2>&1 | head -1)"
  else
    printf '%-12s %-9s %s\n' "$tool" "MISSING" "($kind)"
    [[ "$kind" == "required" ]] && missing=1
  fi
}

for t in "${required[@]}"; do check "$t" required; done
for t in "${optional[@]}"; do check "$t" optional; done

mem_gb=$(awk '/MemTotal/ {printf "%.1f", $2/1024/1024}' /proc/meminfo)
printf '%-12s %-9s %s GB (WSL total; 10+ GB recommended for the full stack)\n' "memory" "info" "$mem_gb"
printf '%-12s %-9s %s\n' "cpus" "info" "$(nproc)"

exit "$missing"
