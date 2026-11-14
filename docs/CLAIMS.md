# Claims register

Every claim that will appear in public text (README, video script, submission form, testing instructions, posts), with its evidence. Add a row when you write the claim. Reconcile the whole table before submitting and before every public post.

Rules: numbers come from a fresh run of their source; device claims name a recorded run; "not merged" means "not shipped"; no always / every / any / never / first / only / real-time without a guarantee in code.

| Claim (exact wording) | Where it appears | Evidence (run ID, command, file:line) | Date checked | Status |
|---|---|---|---|---|
| "<Runs on the Fire TV Stick HD>" | README, video 2:40, form | <run 2026-10-23T07-14, device About screen photo> | <Oct 23> | ok |
| "<125 automated tests>" | README | `npm test` on main: 125 pass, exit 0 | <Oct 25> | ok |
| "<About 12 s from answer to new scene>" | form, video | <screen log of run X: 11.8 s, 12.4 s> | <Oct 23> | ok |
| "<Works on Android TV>" | README | none | <Oct 23> | **cut or label untested** |

## Measured numbers (one per quantity, reuse everywhere)
| Quantity | Value | Source run | Date |
|---|---|---|---|
| <answer → new scene on screen> | <~12 s> | <run id, screen log> | <date> |

## Don't claim
- <Words or features to avoid, and why (for example: "first", "only", a service not in the live path, a platform not run).>
