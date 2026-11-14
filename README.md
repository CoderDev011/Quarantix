# AgentWall

A firewall for AI agents. It tracks where every value came from and how sensitive it is, then checks each tool call against deterministic rules before the action runs. LLMs plan and read; code decides.

> This README is for developers. The judge-facing README is written at the end of the build.

## Start here

1. `AGENTS.md`: rules for every person and coding agent. Read it first.
2. `plan.md`: the master plan. Part 1 has the 24-hour schedule; Part 2 has the step-by-step phases.
3. `docs/contracts.md`: the binding data formats.
4. `docs/features/`: one brief per feature.

## Local setup (inside WSL)

1. Run `bash scripts/check_tools.sh`. It must exit 0 (git, python3, uv, node, pnpm, docker).
2. `uv sync` installs Python 3.12 and every dependency into `.venv`.
3. `cp .env.example .env`, then fill in the keys.
4. Run every check CI would run: `bash scripts/check.sh` (lint, format, types, import rules, tests). It must exit 0 before you commit.

## Run it

| Goal | Command (inside WSL, repo root) |
|---|---|
| Whole stack in Docker: API + console on http://localhost:8000 | `docker compose up -d --build` |
| Also run the local model (demo laptop, 16 GB) | `docker compose --profile local-llm up -d` |
| Is this machine demo-ready? | `bash scripts/doctor.sh` (add `--demo` on the demo laptop) |
| Real-HTTP smoke test (local / built image) | `bash scripts/smoke_api.sh` · `SMOKE_IMAGE=quarantix:demo bash scripts/smoke_api.sh` |
| The hour-6 engine demo, no LLM | `uv run python scripts/demo_core.py` |
| Put demo events into a running console | `QX_API=http://127.0.0.1:8000 QX_AGENT_KEY=<support-agent key> uv run python scripts/demo_feed.py` |
| Regenerate the console's API types | `bash scripts/gen_types.sh` |
| Red-team table (free replay of recorded traces) | `uv run python scripts/redteam.py` |
| Record real traces with the model (costs money) | `LLM_MODE=live uv run python scripts/redteam.py --live --record-traces --modes baseline` |
| A guarded agent we did not write (the drop-in) | `bash scripts/agent.sh devops` (keys come from .env) |
| The firewall's decisions in the terminal (live or replay) | `uv run python scripts/qx_watch.py` · `--runs` · `--replay <run id>` |
| Fake attacker page only (no Docker) | `uv run uvicorn --factory quarantix.attacker:create_app --port 9000` |
| Product page / console / big screen | http://localhost:8000/ · http://localhost:8000/app · http://localhost:8000/arena/screen |

`.env` must set `AGENTWALL_ADMIN_TOKEN` (16+ characters) and `AGENTWALL_AGENT_KEYS` (`agent:key`, keys of 12+ characters). The server refuses to start without them.

## Layout

| Path | Contents |
|---|---|
| `quarantix/` | The product. Generic packages never name a domain |
| `domains/` | Domain packs (YAML + JSON, no Python) |
| `redteam/templates/` | Generic attack templates |
| `proof/scenarios/` | Real-World Proof Suite scenario files |
| `cassettes/` | Recorded LLM responses for replay (committed) |
| `scripts/` | Dev and demo scripts |
| `docs/` | Contracts, feature briefs, decisions, spikes ledger, claims, demo, submission |
