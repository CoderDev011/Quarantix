# F05. Gate and Gate runtime

**Purpose:** one enforcement point used by every way in: interpreter, SDK, MCP gateway and arena.
**Priority:** MUST · **Lane:** Engine · **Checkpoint:** IC1 · **Depends on:** F01, F02, F04, contracts §5–§8

## Provides
- **Gate check** (pure, no I/O): a tool call request → a decision, after applying the agent's mode.
- **Gate runtime:** enforce(request, a way to invoke the tool, optional provenance) → outcome {decision, executed, result, latency}. It raises a "tool blocked" error (carrying the decision) on block, deny or expiry.
- **Approval broker interface:** request(request, decision) → approved, denied or expired. Two implementations:
  - **In-process:** waiting futures keyed by approval id, with resolve(id, verdict, scope).
  - **HTTP:** lives in F12 and implements the same interface.
- **Event sink interface:** emit(event), non-blocking. In-process (F13) and HTTP batch (F12) implementations.
- **A shadow invoker mode:** compute the decision, always execute, and report the decision as "would have" (used by the arena, F15).
- The redaction helper (contracts §8), used for every event preview.

## Behavior

**Modes:**
- **enforce:** apply the decision.
- **monitor:** execute anyway; the decision is logged with enforced = false.
- **off:** skip the check entirely and emit nothing (the true baseline).

**Runtime sequence:**
1. Check.
2. **Allow:** execute.
3. **Ask:**
   - If the runtime is offline → block with `runtime/offline-no-approver`.
   - If a run-scoped approval exists for the same run + tool + rule → execute.
   - Otherwise emit `approval.requested` and wait for the broker:
     - Approved → execute.
     - Denied → block (`runtime/approval-denied`).
     - Expired (120 s by default; 10 s in the arena) → block (`runtime/approval-expired`).
4. **Block:** don't execute; raise.
5. **Tool error:** outcome error, with the error message preview.
6. Emit **exactly one** `tool.call` event per call after the outcome is known, with the argument previews, the context, the decision, the outcome and the latency.

Sync tools are invoked off the event loop. Async tools are awaited with a per-call timeout (default 10 s).

## Edge cases
- The approval is resolved after its expiry → the late resolve is rejected (the API returns 409).
- The broker is unreachable → treat as offline.
- An event sink failure never fails the tool call; count it as a dropped event.

## Performance budget
- Runtime overhead (excluding the tool itself and approval waits): under 2 ms p99.
- `emit` takes under 50 µs.

## Security notes
- Previews pass through redaction **before** they leave the runtime; nothing downstream sees raw values.
- In monitor mode, the UI must make it obvious the call was not stopped (enforced = false).

## Tests
| Test | Asserts |
|---|---|
| block raises and emits one event | |
| monitor executes, enforced false | |
| off emits nothing | |
| ask then approve executes | |
| ask timeout denies | With an injected short timeout |
| offline ask becomes block | |
| run-scope approval reused | |
| secret preview redacted; API key inside a string masked | |
| shadow mode executes everything and records would-block | |
| perf | Overhead p99 < 2 ms (prints the number) |

## Done when
Tests pass. The interpreter (F06), the guard session (F11) and the arena (F15) all call this runtime and nothing else to enforce.

## Freedom
How futures are stored, how timeouts are implemented, and the interfaces' exact shapes.
