# Feature briefs

One file per feature. **An agent working on a feature reads `AGENTS.md`, `docs/contracts.md` and its own brief.** It also reads the "Provides" section of each brief listed under "Depends on".

Every brief has the same sections:

| Section | Content |
|---|---|
| Header | Purpose, priority, lane, checkpoint, depends on |
| Provides | What other features may rely on, described in words. The names are suggestions; the behavior is binding |
| Behavior | The exact rules |
| Edge cases | |
| Performance budget | Must be proven with a `perf` test |
| Security notes | |
| Tests | Name → what it asserts |
| Done when | Observable, on the demo setup |
| Fallback if cut | |
| Freedom | Where a better design is welcome |

| ID | Feature | Priority | Lane | Checkpoint |
|---|---|---|---|---|
| F01 | [Labels and provenance](F01-labels-provenance.md) | MUST | Engine | IC1 |
| F02 | [Tool registry](F02-registry.md) | MUST | Engine | IC1 |
| F03 | [Domain packs and generic tools](F03-domain-packs.md) | MUST | Experience + Engine | IC1/IC2 |
| F04 | [Policy engine](F04-policy-engine.md) | MUST | Engine | IC1 |
| F05 | [Gate and runtime](F05-gate.md) | MUST | Engine | IC1 |
| F06 | [Interpreter and pinned plans](F06-interpreter.md) | MUST | Engine | IC1 |
| F07 | [LLM layer](F07-llm-layer.md) | MUST | AI | IC2 |
| F08 | [Quarantined reader](F08-reader.md) | MUST | AI | IC2 |
| F09 | [Live planner](F09-planner.md) | SHOULD | AI | IC3 |
| F10 | [Naive baseline agent](F10-naive-agent.md) | MUST | AI | IC2 |
| F11 | [Guard mode](F11-guard-mode.md) | MUST | Engine | IC2 |
| F12 | [SDK](F12-sdk.md) | MUST | Platform | IC2 |
| F13 | [Control plane](F13-control-plane.md) | MUST | Platform | IC1/IC2 |
| F14 | [MCP gateway and pinning](F14-mcp-gateway.md) | SHOULD | Platform | IC3 |
| F15 | [Arena back end](F15-arena-backend.md) | MUST | Platform | IC2/IC3 |
| F16 | [Arena phone page and big screen](F16-arena-ui.md) | MUST | Experience | IC3 |
| F17 | [Red Agent](F17-red-agent.md) | SHOULD | AI | IC3 |
| F18 | [Policy Autopilot](F18-autopilot.md) | SHOULD (centerpiece) | AI + Engine | IC3 |
| F19 | [Bring-your-own-domain generator](F19-domain-generator.md) | SHOULD | AI | Freeze |
| F20 | Console: no brief; use `plan.md` Part 1 §6 "F19. Console" (line 1292) + Part 2 Phase 5 (line 2146) | MUST / SHOULD | Experience | IC2/IC3 |
| F21 | Red-team runner and metrics: no brief; use `plan.md` Part 1 §6 "F20" (line 1332) + Part 2 Task 4.6 (line 2129) + `docs/contracts.md` §11, §16 | MUST | Experience | IC2 |
| F22 | Real-World Proof Suite: no brief; use `docs/contracts.md` §12 + the scenario list in `docs/DECISIONS.md` | MUST (subset) | Experience | IC3/Freeze |
| F23 | [Packaging, tunnel, offline, reset](F23-packaging-ops.md) | MUST | Platform | IC3 |
| F24 | Demo, pitch, submission: no brief; use `plan.md` Part 1 §6 "F22" (line 1416) + §10 (line 1512) + Part 2 Phase 8 (line 2335) | MUST | Experience | Freeze |
