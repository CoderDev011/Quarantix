# F07. LLM layer: Gemini, Ollama, cassettes, spend meter

**Purpose:** one way to call models, plus repeatable offline runs and a hard budget.
**Priority:** MUST · **Lane:** AI · **Checkpoint:** IC2 (H11) · **Depends on:** AGENTS.md §7; spike S2 (Gemini) and S1 (Ollama) results

## Provides
A **client interface** with two operations:
- **JSON:** model, system text, user text, an output schema and an effort/temperature preset → a validated object, or a typed error (refused, invalid, timeout, budget exhausted, cassette miss).
- **Tool turn:** model, system text, message history, tool definitions → the model's next message (text and/or tool calls, in a provider-neutral shape), plus token usage.

Three implementations sit behind that interface: a **Gemini client**, an **Ollama client** and a **cassette wrapper**. There is also a **spend meter**: running totals by model, a cap check, and an endpoint feed for the console.

## Behavior

**Gemini client:**
- Uses the official Google Gen AI SDK.
- JSON mode uses the structured-output option documented on 2026-11-14: JSON MIME type plus a JSON schema. Gemini ignores string-length limits, so callers must re-validate.
- Tool turns use Gemini function calling. Spike S2 must confirm this on Flash-Lite before the naive agent depends on it.
- Reads token usage, including thinking tokens if reported, from every response, and passes it to the spend meter.
- A safety block or refusal → a typed "refused" error.

**Ollama client:**
- JSON mode uses Ollama's schema-constrained output.
- Tool turns use Ollama's tool-calling chat API.
- Keep the model loaded: send a keep-alive so it isn't unloaded between attempts.

**Provider-neutral messages:**
- The naive agent and the Red Agent speak one internal message format.
- Each client translates to and from its provider. Tool call ids are generated locally when the provider doesn't supply them.

**Byte-stable prompts:**
- System prompts and tool lists are rendered deterministically: sorted keys, no timestamps, no random ids.
- That lets provider prefix caching work, and makes cassette keys stable.

**Cassette wrapper**, with three modes:
- **live:** call the model.
- **record:** call the model and save the response.
- **replay:** saved responses only.
- The key is a hash of {operation, model, system, user or messages, schema or tools} in canonical form.
- Files live under `cassettes/<first 2 chars>/<key>.json` and are committed.
- A replay miss in CI is an error. In the demo it falls back to live, if the spend meter allows; otherwise it's an error the caller handles.
- **First-turn reuse:** the naive agent's first turn is identical for every arena attempt on the same task (system + tools + task, before any data is read). In record mode it's recorded once and replayed for every later attempt. **This saves one paid turn per attempt.**

**Spend meter:**
- A price table per model, configurable; defaults from the plan's budget table.
- Cost = input tokens × input price + output tokens × output price.
- Persisted to the database (F13's spend table) and exposed as a total.
- Thresholds (configurable):

| Spend | Effect |
|---|---|
| $8 | Economy signal: the arena switches the naive agent to Ollama |
| $10 | Paid calls refused with "budget exhausted" |

- Ollama costs $0, but its calls and latency are counted.

**Concurrency limits** (shared semaphores per provider):

| Provider | Concurrent calls |
|---|---|
| Gemini | 8 |
| Ollama | 1 on CPU, 2 on GPU (from spike S1) |

**Timeouts:** 30 s per call, 2 retries with jittered backoff, only for timeouts, 429s and 5xx errors.

## Edge cases
- The provider returns JSON that fails the schema → one internal re-ask is the caller's job (the reader and planner decide), not the client's.
- A tool call with arguments that aren't valid JSON → returned as an invalid tool call; the naive agent reports it back to the model as an error.
- A 429 rate limit → backoff. If persistent, a typed error, so the arena can show "busy".

## Performance budget
- Overhead per call (excluding the network): under 2 ms.
- A cassette lookup takes under 1 ms.

## Security notes
- API keys come only from the environment and are never logged. Mask them in error messages.
- Cassettes contain only fake-world data. A test scans every cassette for key-like strings.

## Tests
| Test | Asserts |
|---|---|
| replay hit makes no network call | HTTP mocked, zero calls |
| replay miss raises (CI) | |
| record then replay identical | |
| key stable across key order | |
| first-turn reuse | Two arena attempts on the same task: the second one's first turn is a cassette hit |
| spend math | Known usage → known cost; refusal at the cap |
| economy signal at $8 | |
| refused response → typed error | |
| prompt byte-stability | Rendering twice gives identical bytes |
| no secrets in cassettes | Scan for key patterns |

## Done when
The reader and naive agent run in CI with replay and no API key. The console header shows the live spend, e.g. "$0.42 / $10".

## Freedom
The SDK usage details (verify them against the installed SDK version), the internal message format, and the cassette file layout beyond the key rule.
