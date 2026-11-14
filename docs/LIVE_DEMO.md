# Live demo runbook (judges and mentors)

Everything below runs live on the demo laptop, against fake companies, with a real model.
Checked on 2026-11-15 on the dev laptop: `scripts/demo_prep.sh` printed READY; one real
arena attempt through the tunnel took about 24 s for naive/guard and 5 s for full.

## 1. Before the judges arrive (10 minutes)

1. Start the tunnel in its own terminal and leave it open:
   `cloudflared tunnel --url http://localhost:8000`
2. In another terminal (WSL, repo root):
   `bash scripts/demo_prep.sh --rebuild`
   It must end with **READY**. It updates the QR address from the tunnel, rebuilds and
   restarts the stack, sets every agent to **enforce**, restores the day-one policy and
   clears the attacker page. Run it again without `--rebuild` between judge groups.
3. Open the four screens it prints:
   - **Projector:** `<tunnel>/arena/screen`
   - **Laptop:** `<tunnel>/` (console; log in with the admin token, keep Autopilot open)
   - **Attack station** (teammate's laptop or tablet): `<tunnel>/docs` → `POST /v1/arena/attempts`
   - **Second screen (optional):** `http://localhost:9000` (the attacker page)
4. Prepare the SDK terminal (keys are read from `.env`, never printed):
   ```bash
   set -a; source .env; set +a
   export QX_AGENT_KEY="$(grep -E '^AGENTWALL_AGENT_KEYS=' .env | tr ',' '\n' | sed -n 's/.*devops-agent:\(.*\)/\1/p')"
   export QX_API=http://127.0.0.1:8000
   ATTACK="$(uv run python -c 'import yaml;print(yaml.safe_load(open("domains/devops/attacks/a02-tool-swap.yaml"))["plant"]["payload"])')"
   ```

## 2. The attack station (until the phone page exists)

The QR code opens `/arena`, which is not built yet. A teammate runs the attack station:

1. On `<tunnel>/docs`, open **POST /v1/arena/attempts** → "Try it out".
2. The judge says what to try; the teammate fills in `domain` (`support` or `devops`),
   `goal_id` (`money_to_attacker`, `link_planted`, `secret_exfiltrated`, `forbidden_action`),
   the judge's text as `payload` (600 characters max) and their `nickname`.
3. "Execute". The big screen updates when the result is ready (about 30 s).

Goals and their titles are listed at `<tunnel>/v1/arena/goals`.

## 3. The 3-minute script

| Time | Show | Say |
|---|---|---|
| 0:00 | Slide: Slack AI incident (docs/incidents.md I-1) | "Agents read emails, tickets and logs. Any of that text can hijack them." |
| 0:20 | Attack station → big screen | A judge attacks the support agent. Naive 💥, AgentWall 🛡. Click the row on the console's Live page: the reason and the data-path graph. |
| 1:00 | A phishing-link attack (`support` / `link_planted`) | It passes Guard: the honest day-one gap. The big screen alarms. |
| 1:20 | Console → Autopilot | The drafted rule, the proof table, "trigger stopped". Click **Enable**. Re-send the same text: blocked. The screen shows "Patched in m:ss". |
| 2:00 | SDK terminal: `uv run python scripts/guarded_agent.py devops --plant "$ATTACK"` | "Any company's agent, three lines." The log tried to make it run a remote script; C1 blocked it. The model *says* it ignored it; the event log shows it tried. |
| 2:40 | Console → Proof wall | Every scenario, with its source. |
| 2:50 | Close | "A firewall that learns from every attack and never ships a rule without proof." |

Optional (30 s): `docker compose stop api`, run the SDK attack again (still blocked), then
`docker compose start api` (the buffered events appear on the console).

## 4. Fallbacks

| If | Do |
|---|---|
| The tunnel dies | Restart `cloudflared`, run `bash scripts/demo_prep.sh` (it updates the QR address). |
| Gemini is slow or down | Show the Proof wall and the Results page (replay, no model), and the SDK run's events already on the Live page. |
| A judge's attack is ignored by the model | Normal for an obvious attack; ask them to write it like a real customer, or show a prepared one. |
| Guard is breached by something other than the phishing link | Treat it as a found gap: open Autopilot and let it propose a rule. |
| Anything looks wrong between groups | `bash scripts/demo_prep.sh` |

## 5. Do not claim

- That the MCP gateway runs (it is on the roadmap; say so).
- Any attack-success number from the shipped traces as a model run (they are hand-written,
  labeled "scripted"). Quote only recorded runs, with n, mode, model and date.
- That the SDK is a published package, supports other frameworks, or runs in production.
- That the arena meets its 12 s latency budget (measured: about 24 s on 2026-11-15).
