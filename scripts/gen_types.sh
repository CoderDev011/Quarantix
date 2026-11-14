#!/usr/bin/env bash
# Generate the dashboard's TypeScript API types from the control plane's OpenAPI.
# Types are never written by hand (AGENTS.md section 6). Rerun after changing
# quarantix/api/schemas.py or any route. Usage (inside WSL, repo root):
#   bash scripts/gen_types.sh
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
cd "$(dirname "$0")/.."

uv run python - <<'PY' > dashboard/src/api/openapi.json
import json
from pathlib import Path

from quarantix.api.app import create_app
from quarantix.api.settings import Settings

# Building the schema needs no database or real secrets: the app is never started.
settings = Settings(database_url="sqlite+aiosqlite://", admin_token="x" * 16, domains_dir=Path("domains"))
print(json.dumps(create_app(settings).openapi(), indent=2, sort_keys=True))
PY

# openapi-typescript needs TypeScript 5's compiler API; the dashboard itself builds with
# TypeScript 7 (native), which no longer exposes it. So the generator runs isolated.
pnpm dlx --package openapi-typescript@7.13.0 --package typescript@5.9.2 \
  openapi-typescript dashboard/src/api/openapi.json -o dashboard/src/api/types.ts
echo "Generated dashboard/src/api/types.ts"
