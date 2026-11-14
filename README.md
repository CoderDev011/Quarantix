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
4. Run the checks CI runs:
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run pyright`
   - `uv run lint-imports`
   - `uv run pytest -q`

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
