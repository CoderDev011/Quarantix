# AGENTS.md: rules for every coding agent and teammate on Quarantix

This file is canonical. `CLAUDE.md` and `GEMINI.md` only point here. Read this whole file before your first change, then read the files below in this order and **nothing else unless your brief lists it**.

## 1. Read order

1. `AGENTS.md` (this file).
2. `docs/contracts.md`: the binding data formats. Every feature integrates through them.
3. **Your feature brief** in `docs/features/` (one file, e.g. `F05-gate.md`).
4. The briefs listed under "Depends on" in your brief, but only their "Provides" section.
5. **`plan.md`, the master plan (one file).** Its top section explains how to use it, which document wins in a conflict, and a table translating old terms to the current design.
   - **Part 1** is the latest plan (rev 3). Its §8 is the 24-hour schedule per lane: IC1 at H6, IC2 at H11, IC3 at H15, freeze at H18.
   - **Part 2** is the step-by-step implementation phases (Phases 0–9, with numbered tasks).
   - Each brief's "Checkpoint" and "Done when" lines say where your feature fits.
6. **When documents disagree:** `docs/contracts.md` > `docs/DECISIONS.md` > your brief > `plan.md` Part 1 > `plan.md` Part 2.
7. **Features without a brief yet** (console, red-team runner, Real-World Proof Suite, packaging, demo): use the matching sections of `plan.md` Part 1 §6 and Part 2, plus `docs/contracts.md` §11, §12 and §16.
8. `plan.v1.md`, `plan.v2.md` and `plan.v3.md` are history. Don't read them; `plan.md` contains what's still relevant.

## 2. What Quarantix is (one paragraph)

Quarantix is a firewall for AI agents. It tracks **where every value came from** (trusted user, or untrusted data such as a ticket, log, email, web page or MCP tool description) and **how sensitive it is**. It then checks each tool call against deterministic rules before the action runs. LLMs only plan and extract; **code decides**. It protects agents built with our planner (full mode) and agents we never wrote (guard mode: SDK wrap or MCP gateway). It learns from attacks (Autopilot), proves every new rule against the full attack and benign suites before it can ship, and works in any domain. Domains are configuration packs, never code.

## 3. The plan is a brief, not code

- The plan and briefs describe **behavior, data and acceptance tests**. They contain no code on purpose. Do not look for snippets to copy, and do not paste snippets from anywhere without understanding and adapting them.
- **Binding:** everything in `docs/contracts.md` (record names, fields, meanings, enums, versions), every **acceptance test** and every **performance budget** in your brief, and the rules in §5 below.
- **Free:** internal structure, function and class names, algorithms, data structures and libraries (within §6), as long as the binding parts hold. If you find a better design than the brief suggests, use it, and record it in `docs/DECISIONS.md` (date, feature, what, why) in the same commit.
- Changing `docs/contracts.md` needs agreement from all four teammates and a schema version bump. Never change it on your own, even if it looks like a small fix.

## 4. Engineering quality bar

Every change must meet all of these. Reviewers reject changes that don't.

**Performance**
- Meet your brief's budget **and prove it** with a benchmark test marked `perf` that prints the measured number.
- Precompute on load, not per call: compile rules, regexes and schemas once, and index lookups by key. No YAML parsing, regex compiling or schema building on a hot path.
- Never block the event loop. Run sync I/O or CPU-heavy work off-loop. Share connection pools (one HTTP client per process per service).
- Bound everything: queue sizes, buffer sizes, retries, timeouts, payload sizes, loop counts. Every unbounded thing is a denial-of-service bug.
- Batch writes and network sends (events, database inserts). Stream instead of polling where the brief says so.
- Avoid repeated work. Cache by content hash where results are pure (reader extractions, plans, compiled bundles). Reuse identical LLM prefixes (byte-stable prompts).

**Correctness and security**
- Treat every LLM output, request body, YAML file, payload and upstream MCP response as **untrusted input**. Validate it before use.
- Never execute anything an LLM or a user wrote. There is no `eval`/`exec`, no real shell, no dynamic imports from data. The "run command" tool is fake.
- SQL is always parameterized. Compare secrets in constant time. Never print, log or commit a secret. Previews follow `docs/contracts.md` §8.
- Default deny. When unsure, block or ask; never allow by accident.
- Every timeout and limit produces a clear event or error, never a silent hang.

**Reliability**
- Timeouts on every network call. Retry only idempotent operations, with jittered backoff and a cap.
- Make shutdown graceful: flush buffers, cancel background tasks cleanly.
- Results must be deterministic in tests: use replay cassettes, fixed seeds, injected clocks.

**Simplicity**
- Build the smallest design that meets the brief. No speculative abstraction, no plugin systems the brief doesn't ask for, no dead code.
- One responsibility per module, with clear names. Files that change together live together.
- Leave the code clearer than you found it, but do not refactor another lane's feature without its reviewer.

**Testing**
- **Engine features (F01, F04, F05, F06, F11):** strict test-first. Write the brief's tests, see them fail, implement, see them pass.
- **Other back-end features:** the brief's acceptance tests plus edge cases you discover.
- **UI:** smoke tests and one manual check on the target device (phone or projector). No snapshot-test sprawl.
- Run the replay red-team suite before every pull request that touches the engine, guard, AI or domain packs.

## 5. Non-negotiable project rules

1. **The core never names a domain.** The folders `quarantix/core`, `ai`, `engine`, `guard`, `sdk`, `autopilot` must not contain the whole words ticket(s), refund(s), customer(s), invoice(s), repo(s), deploy(s), salary, payroll, order_id. An architecture test enforces this. Domains live in `domains/`, `redteam/` and `policies/` only.
2. **Layering:**
   - Imports point downward only: core ← engine ← guard ← sdk.
   - `ai` depends on core only.
   - `autopilot` may use core, engine and ai.
   - `domains` loader code may use core and engine.
   - `api` uses everything, and nothing imports api.
   - **The reader never imports the registry, engine or guard.** import-linter enforces this in CI.
3. **No model has tool access** except the naive baseline agent and the off-the-shelf MCP client on stage.
4. **The Autopilot drafter and the domain generator never receive untrusted text** (payloads, tickets, logs). They receive only structured statistics or the user's own one-line request.
5. **Every paid LLM call goes through the spend meter.** Hard stop at $10 cumulative.
6. **Never attack real services.** All worlds are fake. Fake tools can reach only the attacker server on port 9000.
7. **Honesty:**
   - Every public number names its sample size, mode, model and date, with evidence in `docs/CLAIMS.md`.
   - Staged or shadow results are labeled as such.
   - Only incidents listed in `docs/incidents.md` (verified, quoted) may appear in public text.

## 6. Stack (do not add dependencies without a line in DECISIONS.md)

- **Back end:** Python 3.12, uv, FastAPI, Pydantic v2, SQLAlchemy Core + aiosqlite, sse-starlette, httpx, PyYAML, the Google Gen AI SDK, the official MCP Python SDK.
- **Tests:** pytest, pytest-asyncio, hypothesis, respx.
- **Quality:** ruff, pyright, import-linter.
- **Front end:** React 19, Vite 8, TypeScript 7, Tailwind 4, React Router 8, shadcn/ui, TanStack Query, zustand, React Flow + dagre, CodeMirror 6, a small QR library. TypeScript types are **generated from the API's OpenAPI**, never written by hand.
- **Packaging:** one Docker image for every Python service, Docker Compose, cloudflared.

## 7. Models and budget (environment variables; never hard-code)

| Role | Default model | Fallback |
|---|---|---|
| Naive baseline agent (arena, red team) | `gemini-3.1-flash-lite` | Ollama `qwen2.5:3b` (economy mode, "weak baseline" toggle) |
| Reader | `gemini-3.1-flash-lite` | `gemini-3.5-flash-lite`, then Ollama |
| Planner (SHOULD), Autopilot drafter, domain generator | `gemini-3.8-flash` | `gemini-4-hydrogen` if quality fails |
| Red Agent | Ollama `qwen2.5:3b` | `gemini-3.1-flash-lite` (only if spend < $6) |

**Budget:** arena ≤ $5 · economy mode at $8 · hard cap $10 · reserve until judging. Before any paid live red-team run, check the balance in the Google console and write it in `docs/SPIKES.md`.

## 8. Workflow

- **Branches:** `<lane>/<topic>` (lanes: `engine`, `ai`, `platform`, `experience`). Small pull requests, under about 400 lines.
- **Reviews:** a PR touching another lane's feature needs that lane's review, and reviews come before new work (target under 10 minutes).
- **CI gates on exit codes only:** lint, types, import rules, architecture test, unit tests, the replay red-team suite. Never gate on grepped output.
- **Commit messages:** "feat(F05): …", "fix(F15): …", "test(F22): …".
- Update `docs/DECISIONS.md`, `docs/CLAIMS.md` and `docs/SPIKES.md` in the same commit as the change they record.

## 9. Status words (use exactly)

| Word | Meaning |
|---|---|
| edited | Code changed |
| tested offline | Unit tests or replay suite pass |
| deployed | Running in the Compose stack |
| verified on demo laptop / verified on phone / verified on projector | Seen working there |
| accepted by team | A teammate confirmed it |

**"Works" and "fixed" are only for the last two.** Always say what ran, where, how many samples, and what was not checked.
