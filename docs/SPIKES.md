# Spikes and paid-session ledger

Each spike has a question, a timebox, a numeric pass line, and a result with evidence (screenshots, numbers, logs). Record pass or fail only after the pass line itself was observed. Friction goes in `FRICTION_LOG.md` as it happens. Spike definitions: `plan.md` Part 1 §7.

## Ledger (Gemini API; budget $12, app hard cap $10)
Before each paid run, write down the balance from the Google console, the expected cost, and whether it fits the allocation. The provider's number wins over this table.

| Date | Who | Purpose | Model / tier | Calls | Cost | Balance after (source) | Result / run id |
|---|---|---|---|---|---|---|---|

Allocation: dev and spikes ≤ $2 · recorded red-team runs ≤ $2 · arena and judging ≤ $5 · reserve $3.
Starting balance: _not yet recorded; read it from the Google console before spike S2_.

## Results
| Spike | Lane | Status | Result |
|---|---|---|---|
| S0 toolchain | Platform | **pass (after installs)** | See below |
| S1 Ollama naive-agent speed | AI + Experience | not run | |
| S2 Gemini capabilities | AI | not run | |
| S3 tunnel + SSE to phones | Platform | not run | |
| S4 shadow vs enforced Guard | Engine | not run (needs F11) | |
| S5 off-the-shelf MCP client | Platform | not run | |

---

## F23 image and stack (2026-11-14, dev laptop)
**Run:** `docker build -t quarantix:demo .`, then `SMOKE_IMAGE=quarantix:demo SMOKE_PORT=18000 bash scripts/smoke_api.sh`.
**Result: pass.** Build exit 0; image 412 MB; runs as uid 10001; no `.env` inside; console assets present. All 9 smoke checks pass against the container: console served, cookie login, policy pack saved, event uploaded, SSE delivered, `Last-Event-ID` resume, bundle ETag/304, stream refuses no token. `docker compose config -q` passes (`api`; plus `ollama` with `--profile local-llm`).
**Not checked:** cold start on the 16 GB demo laptop (budget < 2 min from pulled images); the full stack with Ollama running; the tunnel (spike S3).

## Checkpoint IC1 (hour 6): engine proves the model, no LLM (2026-11-14)
**Run:** `uv run python scripts/demo_core.py` inside WSL on the dev laptop (8 GB RAM, Intel Iris).
**Result: pass.** Exit code 0. The safe plan's refund of ORD-1001 (120.0) was **ALLOWED** by `support/refunds-under-limit`. The naive plan's refund of 4999.0 was **BLOCKED** by `core/C1-untrusted-critical-arg`, with path `order_number <- extract s2.order_number <- get_ticket T-102.text (untrusted)`.
**Suite at the same commit:** `bash scripts/check.sh` exit 0, 190 tests. Budgets measured: evaluate p99 114 µs (≤ 1 ms), gate overhead p99 120 µs (≤ 2 ms), safe plan over 8 records 9.7 ms (≤ 50 ms), compile 100 rules 5.9 ms (≤ 20 ms).
**Not checked:** the demo laptop (teammate's 16 GB machine); anything involving a real LLM.

---

## Spike S0: toolchain on the dev machine (2026-11-14)
**Why:** Phase 0 needs uv, pnpm, Docker and Node inside WSL.
**Run:** `bash scripts/check_tools.sh` inside WSL (Ubuntu). The machine is Windows 11 + WSL2.

| Measure | Result |
|---|---|
| git | 2.53.0 |
| system python3 | 3.14.4. The project uses 3.12.16, installed by uv |
| uv | missing → installed 0.13.8 (`scripts/install_dev_tools.sh`) |
| node | 22.22.1 |
| pnpm | missing; corepack failed to load pnpm 12.18 → installed 10.34.9 via npm |
| docker | 29.9.3 |
| ollama, cloudflared | missing (optional; needed for spikes S1 and S3) |
| WSL memory | **3.7 GB total.** Below the 10 GB needed for the full stack (F23) |
| CPUs | 8 |
| Network from WSL | ~64 KB/s while uv downloaded packages (measured over 20 s) |

**Result:** tools present after the installs. **Open issues:** WSL memory is too low for the full Compose stack plus Ollama, and the network from WSL is slow.
**Correction (2026-11-14):** this dev machine has **8 GB RAM and Intel Iris graphics**. The 16 GB machine belongs to a teammate. Don't raise WSL to 10 GB here; 4–5 GB at most leaves room for Windows and a browser.
**Decision (proposed, awaiting the team):**
- This machine is used for development only: engine, tests and dashboard, run directly with uv and pnpm, with no Docker stack and no Ollama.
- The teammate's 16 GB laptop is the demo machine (Compose, Ollama, tunnel).
- Spike S1 (Ollama speed) runs on the teammate's laptop.
