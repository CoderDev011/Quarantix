# F23. Packaging, tunnel, offline mode, reset

**Purpose:** one command starts everything on the demo laptop in under 2 minutes, with or without venue internet, and the booth resets in under 10 seconds.
**Priority:** MUST · **Lane:** Platform · **Checkpoint:** Compose up by IC2, tunnel and offline by IC3, cold-start measured before the freeze
**Depends on:** F13 (API), F14 (gateway), F03 (domain packs), F07 (cassettes), F15 (arena reset)

## Provides
- One Docker image used by every Python service.
- `docker-compose.yml` with profiles.
- Scripts:
  - **warm cassettes:** records every demo path.
  - **reset:** booth reset.
  - **tunnel:** prints the public URL.
  - **cold-start check:** times start-up.
  - **doctor:** checks the environment.
- `.env.example`.
- The demo-laptop setup steps (Windows + WSL2, 16 GB RAM).

## Behavior

### Image (one multi-stage build)
1. **Stage 1:** build the dashboard with pnpm, from a frozen lockfile.
2. **Stage 2:** install the Python dependencies with uv, from the frozen lockfile and without dev dependencies (using a build cache mount). Copy the package, `domains/`, `policies/`, `redteam/`, `proof/` and `cassettes/`, plus the dashboard build into the API's static folder.
3. Run as a non-root user, with a health check command.

The image tag is the git commit plus `demo`. CI builds and pushes it to GitHub Container Registry on every push to `main`. The laptop pulls it the night before.

### Compose services (same image, different start command)

| Service | Port | Start | Notes |
|---|---|---|---|
| api | 8000 | API server, 1 worker | Health check on /healthz. Every other service waits for it to be healthy |
| mcp-gateway | 8788 | Gateway, HTTP transport | Stdio mode is started by the desktop or CLI client instead |
| mcp-tools | 8100 | MCP tool servers for the devops and code-hosting packs | Holds the "simulate rug pull" switch |
| attacker | 9000 | Attacker server | Its log goes to a volume |
| guarded-agent | — | The SDK-guarded support agent, looping its task every 60 s | Keeps the Live feed alive |
| ollama | 11434 | Ollama | Profile `local-llm`. Model pre-pulled into a named volume. Memory limit 4 GB |
| tunnel | — | cloudflared quick tunnel → api | Profile `public`. Writes the public URL to the API (an admin endpoint), so the QR code is always right |

- **Volumes:** `data/` (SQLite and the attacker log), `ollama-models`, `cassettes/` (bind mount, so new recordings are kept).
- **Environment:** from `.env`. Default LLM mode is record. Offline switch: LLM mode replay.
- **Resource limits:** api 1 GB, gateway 256 MB, tools 256 MB, attacker 128 MB, ollama 4 GB. That totals about 6 GB, which leaves room for the browser and projector output on a 16 GB laptop.

### Demo-laptop setup (Windows + WSL2), done once and written into `docs/DEMO.md`
1. **WSL2 memory:** in the Windows user's `.wslconfig`, allow at least 10 GB of memory and 4 processors. Restart WSL.
2. **Docker:** Docker Desktop with WSL integration enabled for the Ubuntu distro, or Docker Engine inside WSL. Pick one, and record which.
3. **Ports:** localhost forwarding from WSL to Windows is on by default. Open http://localhost:8000 in the Windows browser.
4. **Code location:** keep the repository inside the WSL file system (`/home/...`), not on `/mnt/c`, for build speed.
5. **Before the event:** pull the image and the Ollama model on fast internet.

### Offline mode
- The **warm-cassettes** script runs every path the demo can take, in record mode, and commits the results:
  - every domain's pinned task;
  - every arena example and hand-tuned attack, against all three defenders;
  - both Autopilot flows;
  - the Proof Suite MUST scenarios;
  - the domain-generator samples.
- With LLM mode replay and Wi-Fi off, the whole judge demo runs. Only brand-new arena payloads need live models; those fall back to Ollama, which is local.
- The console header shows "OFFLINE (replay)" when replay mode is on.

### Booth reset (under 10 s, one button or one script)
1. Restore each domain's day-one policy and remove the autopilot packs (bundle version bumps).
2. Clear pending approvals and open proposals.
3. Clear the attacker log and the arena's "patched" counters. Keep the leaderboard unless the "full reset" flag is set.
4. Reload the world templates.
5. Emit `policy.changed` so agents and screens update.

**Refuse to run while an arena job or proof is in progress.** Wait up to 15 s, then report what's still running.

### Tunnel
- The quick tunnel needs no account.
- The **tunnel** script starts it, extracts the public URL and posts it to the API.
- **Fallback:** if the tunnel fails at the venue, a laptop hotspot + the laptop's LAN address. The **doctor** script prints that address, and the QR code switches to it.

### Doctor script
Checks and prints pass or fail for:
- Docker running.
- Free memory ≥ 6 GB.
- Ports free.
- `.env` present, and the keys set (shown masked).
- The Gemini key valid, with one tiny free-tier call.
- The Ollama model present.
- The cassette count.
- The current spend versus the cap.
- The database writable.
- The tunnel reachable.

It **exits non-zero on any failure** (gate on the exit code).

### .env.example
Placeholders only:
- The Gemini API key.
- The model ID per role.
- The Ollama URL and model.
- The LLM mode.
- The admin token.
- The agent keys list.
- The database URL.
- The spend thresholds.
- Arena limits.
- The public base URL.

## Edge cases
- A port is taken → the doctor script names the process.
- The Ollama model is missing → the doctor fails; the arena runs in Gemini-only mode, with a warning.
- The clock skews after a laptop sleep → no effect (monotonic timers).

## Performance budget
- Cold start from a pulled image to a healthy API: under 2 minutes. Measured three times; the median goes in `docs/SPIKES.md`.
- Booth reset: under 10 s.

## Security notes
- `.env` is never baked into the image. A test or CI step checks the image has no `.env`.
- The admin token is required for every admin route through the tunnel (verified from a phone on mobile data).

## Tests and checks
| Check | Pass |
|---|---|
| image builds in CI and contains no `.env` | exit code 0 |
| compose up → all health checks green | within 2 min |
| offline demo run | the full judge demo with Wi-Fi off |
| reset | under 10 s; the day-one gap is back (the phishing scenario breaches Guard again) |
| tunnel from a phone on mobile data | `/arena` loads in under 3 s; admin routes refuse without the token |
| doctor | exits non-zero when the Gemini key is removed |

## Done when
On the demo laptop:
- From cold: pull → up → healthy in under 2 min.
- The full demo runs offline.
- A phone reaches the arena through the tunnel (or the hotspot fallback).
- The reset works in under 10 s.

All recorded in `docs/SPIKES.md`.

## Fallback if cut
Run the services directly with uv and pnpm in four terminals (documented in `docs/DEMO.md`). Never cut offline replay.

## Freedom
Base images, the build-cache strategy and script implementation language.
