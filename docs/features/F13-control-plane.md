# F13. Control plane: store, event bus, SSE, API, auth

**Purpose:** see and steer everything from one place.
**Priority:** MUST · **Lane:** Platform · **Checkpoint:** store and bus by IC1, endpoints by IC2 · **Depends on:** contracts (all sections)

## Provides
- The HTTP API below.
- An **in-process event sink** and **approval broker** (for runs inside the API: full mode, arena, proof suite).
- A **bundle service**: the current bundle and its version, plus change notification.
- A **spend total** (from F07).

## Behavior

**Store** (SQLite in WAL mode; on connect: WAL journal, normal sync, 5 s busy timeout; parameterized SQL only):

| Table | Key columns | Indexes |
|---|---|---|
| runs | id, agent, mode, request or task, status, plan, result, created, finished | agent + created |
| events | seq (key), event id (unique), run id, agent, kind, decision, time, body | run id; agent + seq; kind + seq |
| approvals | id, run id, agent, tool, rule, reason, previews, status, scope, created, resolved, resolved by | status |
| policy_packs | name, yaml, enabled, version, origin, updated | — |
| agents | name, key hash, mode, last seen, policy version, SDK version, dropped events | — |
| arena_attempts | contracts §13 | time; points; player |
| players | id, nickname, points, attempts, created | points |
| proposals | contracts §14 | status |
| mcp_pins | contracts §15 | server + tool |
| spend | provider, model, input tokens, output tokens, cost, time | time |
| reports | id, kind (redteam, proof), created, body | kind + created |

Event inserts ignore duplicate event ids, so SDK retries are idempotent.

**Event bus:**
- Sequence numbers come from an in-process counter that starts at the highest stored seq.
- Broadcast to subscribers (each with a bounded queue of 1,000).
- A writer task drains to the database every 100 ms or 200 events, in one transaction.
- A subscriber whose queue fills up is dropped and sent `resync`.

**SSE stream:**
- Filters: since-seq, agent, run, kind.
- **Order:** subscribe first, then the database backlog, then live events, de-duplicated by seq.
- The SSE id = seq, so the browser's automatic resume works.
- Keep-alive comment every 15 s.
- **Two streams:**
  - the **admin stream** (full events);
  - the **public arena stream** (sanitized arena events only, never raw payloads).

**Long-polls:** the bundle and approval waits are notify-on-change (a condition variable per agent or approval), so they return within milliseconds of a change.

**Endpoints:**

| Method and path | Who | Purpose |
|---|---|---|
| GET /healthz | anyone | Liveness check |
| POST /v1/runs; GET /v1/runs/{id} | admin | Start a full-mode run (task id or natural-language request), in the background; read its status, plan, step states and answer |
| POST /v1/check | agent | Dry-run decision |
| POST /v1/events:batch | agent | ≤ 500 events, compression allowed, idempotent |
| GET /v1/events/stream; GET /v1/events | admin | SSE stream; paged history |
| POST /v1/approvals; GET /v1/approvals/{id}?wait=25 | agent | Create; long-poll |
| GET /v1/approvals; POST /v1/approvals/{id}/resolve | admin | List; approve or deny, once or for this run (a second resolve → 409) |
| GET /v1/policies/bundle?agent=&wait=25 | agent | Long-poll with ETag; 304 when unchanged; counts as the heartbeat |
| GET, PUT /v1/policies/packs/{name}; POST /v1/policies/validate | admin | Read; save (compiled first; errors carry the line); validate only |
| POST /v1/policies/reset-day-one | admin | Booth reset: restore the day-one packs and remove autopilot packs |
| PUT /v1/agents/{agent}/mode; GET /v1/agents | admin | Change the mode; list agents (online = last seen < 35 s) |
| GET /v1/spend | admin | Spend meter |
| /v1/arena/* | public / admin | F15 |
| /v1/autopilot/* | admin | F18 |
| /v1/mcp/* | admin | F14 |
| /v1/domains/* | admin | F19 (generate, list, load) |
| /v1/proof/* | admin | F22 (list scenarios, run one, run all, results) |
| POST, GET /v1/reports | admin | Upload and read red-team and proof reports |

**Auth:**
- Agent keys come from an environment list ("agent:key"). Only their hashes are stored, and comparisons are constant time. **The key decides the agent name.**
- The admin token travels in a cookie (set by a tiny login form) or a header.
- Arena routes are public, with rate limits (F15).

**Static files:** the built dashboard is served at "/" with an SPA fallback. "/arena" and "/arena/screen" are public routes; everything else needs the admin login.

## Edge cases
- The database is locked under a burst → the busy timeout plus a single writer prevents errors.
- A malformed event in a batch → reject only that event and report its index.
- A request body over 1 MB → 413.

## Performance budget
- Event → console: under 300 ms p95.
- 500 events → at most 5 transactions.
- Bundle long-poll returns under 100 ms after a change.
- The API holds 50 events/s for 5 minutes without its queues growing.

## Security notes
- Never trust an agent name in a body.
- Admin routes are never reachable through the public tunnel without the token. Test through the tunnel URL.
- Error messages never echo secrets.

## Tests
| Test | Asserts |
|---|---|
| idempotent inserts | |
| history order and filters | |
| no secret in the database file | Run a scenario with a secret argument, then search the database bytes |
| seq rises under concurrency | |
| batched writes | |
| SSE resume: no gap, no duplicate | |
| slow subscriber gets resync | |
| agent key binds the agent name | |
| bundle 304 and fast return on change | |
| approval second resolve → 409 | |
| invalid pack returns its line | |
| public arena stream has no raw payloads | |
| admin route rejected without the token | |
| load test 50 events/s for 5 min | perf |

## Done when (IC2)
A full-mode run started with one request shows `run.started` through `run.finished` on the SSE stream and in the console feed.

## Freedom
The framework structure, router layout, and how the writer and broadcaster are organized.
