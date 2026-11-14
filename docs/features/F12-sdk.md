# F12. SDK: local enforcement, policy sync, fail-safe

**Purpose:** the drop-in. An existing agent adds about three lines and is protected, with decisions made next to the agent, even if the cloud is down.
**Priority:** MUST · **Lane:** Platform · **Checkpoint:** IC2 · **Depends on:** F02, F04, F05, F11, F13 (API shapes)

## Provides
- **Init:** API key, agent name, control-plane URL, cache folder (default `~/.quarantix/<agent>/`), optional registry or domain pack.
- **Guard wrap:** a list of tool functions → wrapped functions **with identical signatures**. Each call goes through the current guard session.
- **Session:** a context block creating a guard session, optionally with the user's message. Tracked per task or thread, so concurrent conversations never mix.
- **HTTP event sink** and **HTTP approval broker**: implementations of F05's interfaces.
- **Bundle sync:** online status, time of the last successful sync, the current bundle.

## Behavior

**One background worker** handles all network traffic. The agent's event loop is never blocked by the network. Sync agents get a daemon thread with its own loop.

**Policy sync:**
1. Long-poll the bundle endpoint with "if none match" = the current version and a 25 s wait.
2. On a new bundle:
   - Verify its content hash.
   - Write it to the cache atomically (temporary file, then rename).
   - Swap it in.
3. **Every poll is also the heartbeat.**

**Event shipping:**
- A bounded buffer of 10,000 events.
- Flush every 250 ms or every 100 events, compressed.
- Exponential backoff up to 10 s.
- When the buffer is full, drop the oldest events and count them. The count is shown on the console's agent card.

**Approvals:** create the approval, then long-poll its status until it's resolved or 120 s pass.

**Fail-safe:**

| State | Behavior |
|---|---|
| Online, fresh bundle | Normal |
| Offline, verified cached bundle | Decide locally; ask becomes block; events buffered |
| Offline, no bundle ever loaded | Core rules only; every high-risk sink blocked |
| Cached bundle older than 24 h | High-risk sinks blocked |

**The "guarded agent" scripts:** for support and devops, about 10 lines each. They load the domain pack, wrap the naive agent's invoker and loop over the task. These scripts **are** the drop-in pitch slide.

## Edge cases
- The control plane restarts mid-long-poll → reconnect with backoff.
- Clock skew → use monotonic time for ages.
- A corrupted cache file → ignored, a warning event, treated as no bundle.

## Performance budget
- A policy change reaches the SDK in under 1 s.
- The wrap adds under 2 ms per call (excluding approvals).

## Security notes
- The API key is never logged.
- The cached bundle is verified by hash before use. (Signing is a post-hackathon roadmap item.)

## Tests
| Test | Asserts |
|---|---|
| policy change applies < 1 s | HTTP mocked |
| offline uses cached bundle | |
| offline ask becomes block | |
| cold offline blocks high-risk | |
| events buffer and flush on reconnect | |
| wrapped function keeps its signature | |
| corrupted cache ignored | |

## Done when (IC2)
- A guarded support agent runs in a terminal, and the console shows its events live.
- A rule edit changes its behavior within 1 s.
- Stopping the API still blocks the attack; restarting it delivers the buffered events.

## Freedom
The threading model and the internal queue design.
