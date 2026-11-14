# F04. Policy engine

**Purpose:** turn a labeled tool call into allow, ask or block, deterministically.
**Priority:** MUST · **Lane:** Engine · **Checkpoint:** IC1 · **Depends on:** F01, F02, contracts §5, §6, §9

## Provides
- **Compile a pack:** YAML text → a compiled pack, or a compile error with line and column.
- **Bundle:** all enabled packs together, with a content-hash version, and a per-agent view (rules indexed by tool, mode, allowed link hosts) computed once per version.
- **Evaluate:** a tool call request + its tool spec + the agent's view → a decision (contracts §6).
- **Answer check (C4):** text + its label + allowed hosts → cleaned text plus the list of removed links.
- **Reason templates:** one plain-language sentence per rule.

## Behavior

**Core rules** (only for sink and both-kind tools; source tools are never blocked):

| Rule | Fires when | Decision |
|---|---|---|
| C1 untrusted critical argument | A critical argument is untrusted with evidence exact or traced | block |
| C1, ambiguous | A critical argument is untrusted with evidence ambiguous | ask |
| C2 confidentiality exceeds audience | The highest argument confidentiality is above the audience clearance (the audience is resolved from the arguments via F02) | block |
| C3 untrusted context, high risk | The context is untrusted and the risk is high, **or** a critical argument is untrusted with evidence inferred | ask |
| C4 link leak (answers only) | A URL or markdown image in the final answer whose host is not allowed, while the answer's confidentiality is internal or higher | remove the link |

**Combine (exact order):**
1. Core result = the most severe core rule that fired (allow < ask < block), or allow if none.
2. Pack matches = the rules under this exact tool name plus the wildcard rules, whose conditions all hold.
3. A core block → **block**. Nothing relaxes a core block.
4. Any matched pack block → **block**.
5. Core ask:
   - Any matched pack ask → **ask**.
   - Otherwise, a matched allow rule **naming this exact tool** → **allow**.
   - Otherwise → **ask**.
6. Core allow → ask if any matched pack ask, otherwise allow (by the matched allow rule, or `default`).
7. The decision lists every fired and matched rule. The reason comes from the deciding rule's template.

**Reason template examples:**
- C1: "The amount was written by ticket T-102 (untrusted), and issue_refund uses it to decide how much money moves."
- C2: "This message contains private data from acme/pricing-engine, but it is going to a public pull request."
- C3: "Untrusted content shaped this request, so a person should approve this high-risk action."

**Compilation:**
- Validate every key and operator.
- Turn every condition into a ready-made check closure, once.
- Precompile regexes.
- The `has_link_outside_allowed_hosts` operator uses one precompiled URL matcher and compares hosts case-insensitively, ignoring "www.".
- The `not_trusted` integrity value matches untrusted (any evidence).

## Edge cases
- A condition on a missing argument → does not hold.
- A number compared with text → does not hold, and never crashes.
- An empty pack is valid.
- Duplicate rule names in one pack → compile error.
- A wildcard allow → compile error (the brief forbids it).

## Performance budget
- p99 under 1 ms for evaluation with 100 rules and 6 arguments.
- Compiling a 100-rule pack takes under 20 ms.

## Security notes
- No rule may relax a core block: test it with every pack rule shape.
- The compiler is fed by humans **and by Autopilot**. Fuzz it with random YAML and check it never crashes and never produces a rule that does more than its template allows.

## Tests
| Test | Asserts |
|---|---|
| C1 exact blocks | Kind block, rule C1, offending argument named |
| C1 traced blocks / ambiguous asks / inferred asks via C3 | Evidence levels map correctly |
| C2 blocks private → public, allows private → internal | |
| C3 asks | |
| named allow relaxes C3 | The support refund rule turns ask into allow |
| wildcard allow rejected | Compile error |
| nothing relaxes core block | For each pack rule type |
| pack block beats core ask | |
| sources never checked | |
| link operator | Detects a markdown link to an unknown host; ignores allowed hosts |
| reason names argument and source | |
| compile error line number | A bad operator on line 7 → error line 7 |
| bundle version | Same content → same version; any change → new version |
| fuzz compile | 1,000 random YAML documents: no crash, only errors or valid packs |
| perf | 100-rule evaluation p99 < 1 ms (prints the number) |

## Done when
All tests pass. The combine order is mirrored in `docs/DECISIONS.md`. The core demo script (F06) shows a C1 block with its reason.

## Freedom
The compilation strategy (closures, a decision table, bitsets…), as long as the semantics and budgets hold.
