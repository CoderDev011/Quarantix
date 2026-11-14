#!/usr/bin/env bash
# Run the same Python checks as CI. Exits non-zero on the first failure.
# Usage (inside WSL, from the repo root): bash scripts/check.sh
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
export LLM_MODE=replay
cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "ruff check";        uv run ruff check .
step "ruff format";       uv run ruff format --check .
step "pyright";           uv run pyright
step "import layering";   uv run lint-imports
step "pytest";            uv run pytest -q "$@"

printf '\nAll checks passed.\n'
