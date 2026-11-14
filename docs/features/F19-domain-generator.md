# F19. Bring-your-own-domain generator

**Purpose:** the strongest answer to "does it really work in any domain?". A judge types a domain, and within about 60 seconds AgentWall is protecting a brand-new agent in it, with zero engine changes.
**Priority:** SHOULD (the hand-checked hr-payroll pack is the guaranteed fallback) · **Lane:** AI · **Checkpoint:** before the freeze (H18) · **Depends on:** F03 (pack format and validator), F07, F09 (validator), F15, F21

## Provides
| Method and path | Purpose |
|---|---|
| POST /v1/domains/generate | Domain description (≤ 200 characters) → a draft pack id and status |
| GET /v1/domains/drafts/{id} | The draft, its validation results and the label review list |
| POST /v1/domains/drafts/{id}/confirm | A human confirms the flagged labels → the pack is loaded live, its goals appear in the arena, and template attacks are instantiated |

Plus a console page section "New domain" (in F20).

## Behavior
1. **Input:** the judge's one-line description, treated as a user request. It is the only free text the generator sees.
2. **Generation**, two structured-output calls to the generator model (≈ $0.02–0.04 total):
   - **Call 1, the skeleton:**
     - Stores, each with authored-by and fields (type, confidentiality, free text or not).
     - Tools, **chosen only from the eight generic behaviors**, with parameters, risk, audience or audience rule, and critical arguments.
     - One task, with its plant target.
     - 2–3 goals from the five goal kinds.
     - The agent's system prompt.
   - **Call 2, seed data:** ≤ 12 records per store, using only fake names and `example.com` / `.test` domains, plus one secret value if a read-secret tool exists.
3. **Deterministic hardening** (our code, after generation), which **overrides** the model:
   - Outsider-authored text → untrusted.
   - Every sink → at least medium risk.
   - Money-like, destination and channel arguments → critical.
   - Unknown audiences → external.
   - Any field the model marked trusted that comes from an outsider store → untrusted.
   - Seed data with non-fake domains → rewritten to `example.com`.
4. **Pinned plan:** built by a deterministic **plan template** per pattern (list → extract → lookup → act → report), filled from the skeleton. Then validated (F09). If no template fits, the domain runs in guard mode only, and the console says so.
5. **Policy pack:** core rules only, plus an empty day-one pack. Autopilot can propose more later.
6. **Label review:**
   - The console lists every label decision with a reason ("text from 'patient messages' is outsider-authored → untrusted").
   - Anything the hardening changed is highlighted.
   - The human clicks Confirm. Nothing loads before that click.
7. **Activation:**
   - Load the pack and register its agent.
   - Instantiate the generic attack templates whose requirements match (F21).
   - The arena shows the new mission cards immediately.
   - Run a 5-attack quick proof (baseline, guard, full) and show the table.

## Edge cases
- A vague domain ("stuff") → ask the user for a clearer description; don't generate.
- A domain that would need a new behavior (e.g. "control a drone") → map it to the closest generic behaviors (`run_command`, `ledger_write`) and say so in the review.
- Generation fails validation twice → fall back to the hr-payroll pack with a message.

## Performance budget
- Generate + harden + validate: under 30 s.
- Confirm → arena-ready with a quick proof: under 60 s.

## Security notes
- The generator never sees payloads or world data.
- The hardening rules are the security boundary, not the model's labels. Test each rule.

## Tests
| Test | Asserts |
|---|---|
| hardening overrides a trusted outsider field | |
| hardening makes a money argument critical | |
| non-fake domains rewritten | |
| nothing loads before confirm | |
| generated pack passes F03 validation | Recorded: 3 sample domains (hospital records, school fees, logistics) |
| goals appear in the arena after confirm | |

## Done when
On the demo laptop, "hospital patient records" goes from typed to arena-ready, with a quick-proof table, in under 60 s (recorded), and a phone can attack it.

## Fallback if cut
The hr-payroll pack, shown as "a third domain added with zero code: one folder of YAML".

## Freedom
The prompt design, plan-template coverage, and the review UI.
