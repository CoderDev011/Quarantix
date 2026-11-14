# F06. Interpreter and pinned plans (full mode)

**Purpose:** execute a plan with exact label propagation, so untrusted data can never steer an action unnoticed. This is the column that should show 0% attack success.
**Priority:** MUST · **Lane:** Engine · **Checkpoint:** IC1 · **Depends on:** F01–F05, F08 (reader interface only), contracts §4

## Provides
- **Run plan:** a plan, the domain registry, the Gate runtime, a reader and a run context (run id, agent, limits) → a run result:
  - status: ok, partial or failed;
  - the answer and the answer's label;
  - the state of each step: ok, blocked, skipped (with the step it depended on) or error (with a message).
- **Core demo script:** a terminal script, using the support pack's world and a stub reader, that prints:
  - one ALLOWED line with its rule;
  - one BLOCKED line (rule C1) followed by its chain: amount ← extract s3 ← ticket T-102 (untrusted).

## Behavior

**Scopes:**
- Variables live in immutable chained scopes. Each loop iteration gets a child scope.
- Only a loop's **collect** value leaves the loop. It is gathered into a list bound to the loop's output. The list's label is the join of the item labels plus the container label.

**Literals** are trusted/public, with source planner.

**Context label:**
- Inside an `if`: the outer context joined with the condition's label.
- Inside a `for_each`: the outer context joined with the list container's label.
- Restored after the block.

**Tool results:**
- An endorsed tool's result gets the tool's output label (plus field labels).
- Otherwise: the output label joined with all argument labels and the context, plus field-label overrides.
- Each result gets a provenance node whose parents are the argument nodes.

**Sink calls:**
- Build the tool call request (mode full, evidence exact) and enforce it through the runtime.
- A block marks the step blocked and binds its output to a BLOCKED marker.
- **Any later step that references a BLOCKED or failed value is skipped**, naming the step it depends on. Independent steps continue.

**Extract steps** call the reader. Its outputs carry the source's label (stamped by the reader).

**Loops:**
- At most 4 concurrent iterations; events carry the iteration index.
- More than 50 items → the first 50 run and a `limit` event is emitted.

**Format** renders the template. Its output label is the join of the value labels.

**Return:**
- Render the value.
- Run C4 (F04's answer check) with the pack's allowed hosts.
- Emit `answer.link_stripped` for each removed link.

**Limits:** ≤ 40 steps, depth ≤ 3, ≤ 100 tool calls, 180 s wall-clock. Exceeding one ends the run with a `limit` event and status partial or failed.

**Pinned plans:** loaded from the domain pack by task id. Validated at pack load (F03 rule 6). They never call the planner.

## Edge cases
- A reader result of all nulls → `truthy` is false, so the else branch runs.
- A tool error → step error, and its dependents are skipped.
- A loop over an empty list → collect gives an empty list.
- A format value that is BLOCKED → the format step is skipped.

## Performance budget
- Interpreter overhead per step, excluding tools and LLM: under 0.5 ms.
- The support pinned plan over 8 tickets with a cached reader: under 50 ms end to end.

## Security notes
- No string from data can become a step, a tool name or an argument name. The plan is fixed before data is read; data only fills values.
- Branch and loop context raising is what catches control-flow steering. Do not skip it as an optimization.

## Tests
| Test | Asserts |
|---|---|
| naive plan blocked | A plan that extracts the amount from text → C1 block; the genuine path allowed |
| branch raises context; context restored | |
| endorsement drops argument taint | |
| blocked value skips only dependents | Step states exactly as expected |
| loop truncation | 60 items → 50 run + one limit event |
| loop scopes don't leak | |
| C4 strips exfil link | A markdown image to the attacker host carrying private data is removed |
| tool-call limit | |
| support plan zero approvals | All genuine tickets → refunds happen, no ask events |
| devops plan | A restart happens only for a trusted, known service |
| property: no unblocked untrusted critical argument | Random well-formed plans over generic tools never execute a sink with an untrusted critical argument |

## Done when (IC1)
The core demo script prints the ALLOWED and BLOCKED lines on the demo laptop, with no LLM involved.

## Freedom
The evaluation strategy (a recursive walk, compiling to a task graph for more parallelism, etc.), as long as the label semantics, event order per call and limits hold.
