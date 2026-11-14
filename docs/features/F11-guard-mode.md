# F11. Guard mode: value tracer and guard session

**Purpose:** protect agents whose code we did not write, with no plan and no planner, while keeping approvals rare.
**Priority:** MUST · **Lane:** Engine · **Checkpoint:** IC2 · **Depends on:** F01, F02, F04, F05

## Provides
- **Value tracer:**
  - Index a value with its label, or index a user message (trusted).
  - Trace a value → {evidence (traced, ambiguous, or unknown), integrity, confidentiality, matched sources, matched tokens}.
- **Guard session** (one per agent conversation or MCP client connection):
  - Observe the user's message.
  - Call a tool (name, arguments, a way to invoke it) → the result, or a "tool blocked" error.
  - Check the final answer (C4).
  - Its current **taint** (a label).
  - Operates in **enforce** or **shadow** mode.

## Behavior

**Normalization** (before indexing and tracing):
1. Unicode NFKC.
2. Remove zero-width characters (U+200B–U+200F, U+2060, U+FEFF).
3. Case-fold.
4. Collapse whitespace.

**Tokens of a value:**
- The whole value, if it is 4–200 characters.
- Every URL, and its host.
- Every email address.
- Every number with ≥ 3 significant characters, canonicalized ("4,999.00" becomes "4999").
- Every identifier-like word of ≥ 8 characters.
- Every IBAN-like or account-like string.

**Index:** for each token, the trusted sources, the untrusted sources and the highest confidentiality seen.

**Trace:**

| Matched tokens | Result |
|---|---|
| None | **unknown** |
| At least one only in untrusted sources | **traced, untrusted** |
| Some in both kinds of source, none only in untrusted | **ambiguous** |
| All only in trusted sources | **traced, trusted** |

Confidentiality = the highest among the matched tokens.

**Guard session call:**
1. For each argument, trace it:
   - Unknown → integrity = the session taint's integrity, evidence **inferred**.
   - Otherwise → the trace result.
2. The context is the taint.
3. Build the tool call request (mode guard) and enforce it through the Gate runtime.
4. Source tools aren't checked, but still emit an allowed event (the feed shows reads).
5. After the result arrives:
   - Label it from the tool spec (field labels per field and per list item).
   - Index it.
   - Join it into the taint.
   - Add provenance nodes, linking each argument to the result nodes its tokens matched.

**Shadow mode:** every call executes; the decision is recorded as "would have". The first would-block or would-ask step is reported (the arena uses this).

## Edge cases
- Short or common values ("1", "yes", "ok") → unknown.
- A zero-width-split payload is still traced.
- A genuine amount that also appears in untrusted text → ambiguous → ask. This is why seed data avoids it.
- A paraphrased leak → unknown → inferred → C3 ask on high risk. That is the documented limitation.

## Performance budget
- Tracing a 10 KB argument: under 5 ms.
- Indexing a 50 KB result: under 10 ms.
- The index for one session stays under 5 MB (cap it, evicting the oldest results first, and log a limit event).

## Security notes
- Tracing may only make decisions **more precise** than session taint, never less safe. When tracing is unsure (unknown), the inferred taint applies.

## Tests
| Test | Asserts |
|---|---|
| verbatim untrusted traced | |
| user-message value trusted | |
| both sources ambiguous | |
| short values unknown | |
| zero-width payload traced | |
| number canonicalization | "4,999.00" equals "4999" |
| private identifier raises confidentiality | Code-hosting identifiers |
| shell command from log blocked by C1 | devops |
| genuine refund allowed via the pack | support, zero approvals |
| untraced high-risk after untrusted read asks | |
| shadow mode reports the first would-block step | |
| phishing link copied into an internal message is NOT blocked by core rules | Documents the day-one gap; this test flips once Autopilot's rule is enabled |
| perf | Tracer budgets (prints the numbers) |

## Done when
The naive support agent wrapped in guard mode blocks the value-swap attack with C1 and completes the benign task with zero approvals. The phishing-link gap is reproduced deterministically.

## Freedom
The token index structure (hash maps, tries) and the tokenizer implementation. Rolling hashes for long text are welcome, but are a COULD.
