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
