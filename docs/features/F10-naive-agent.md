# F10. Naive baseline agent

**Purpose:** the realistic "what companies run today" agent. It is the unprotected baseline, and also the agent that guard mode wraps.
**Priority:** MUST · **Lane:** AI · **Checkpoint:** IC2 · **Depends on:** F02, F03, F07

## Provides
**Run:** request + domain registry + an invoker + model choice → result {final answer, transcript, tool calls made, turns, latency}.

**Invoker** = a way to execute one tool call. Three kinds:
- **plain** (baseline);
- **guarded** (F11 guard session, enforce);
- **shadow** (F11 guard session in shadow mode, for the arena).

## Behavior

**Loop:**
1. Send the system prompt (from the domain pack), the tool definitions (from the catalog) and the request.
2. Execute **all** tool calls in a turn **concurrently**.
3. Return all the results together in the next message.
4. Repeat until the model answers with text, or 8 turns pass. The arena uses 8; the red-team suite uses 12.

**The system prompt is a realistic production prompt with no injection defenses.** That's on purpose, and the README says so.

**A blocked tool** returns an error result to the model: "Blocked by Quarantix: <reason>". The agent may continue or explain. It does not crash.

**An invalid tool call** (unknown tool, bad arguments) → an error result back to the model, counted in the transcript.

**First-turn reuse:** in record and replay modes, the cassette layer (F07) serves the identical first turn.

**Model choice:**
- `gemini-3.1-flash-lite` by default.
- Ollama `qwen2.5:3b` in economy mode, offline, or when the **weak-baseline toggle** is on. The toggle is shown in the console and the arena screen as "Baseline model: …".

## Edge cases
- The model calls the same tool repeatedly in a loop → the turn limit stops it.
- The model answers immediately with no tools → valid; usually a benign failure, recorded as such.
- Parallel tool calls that write the same ledger → serialized by the executor's per-world lock.

## Performance budget
Arena p50 for one naive run on Flash-Lite: under 8 s for support, under 6 s for devops (measured, 10 samples, in `docs/SPIKES.md`).

## Security notes
This is the only component, besides the off-the-shelf MCP client, that gives a model tools. Its tools always run against a cloned fake world.

## Tests
| Test | Asserts |
|---|---|
| parallel results in one message | Fake model |
| blocked tool → error result | |
| turn limit | |
| invalid tool call handled | |
| benign task completes | Recorded: support and devops |

## Done when
Both baselines complete their benign task, and at least 3 library attacks per MUST domain visibly succeed against the baseline (the attacker page lights up). Recorded.

## Freedom
The loop structure and how tool definitions are rendered per provider.
