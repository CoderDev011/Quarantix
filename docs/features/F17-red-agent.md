# F17. Red Agent: adaptive attacker

**Purpose:** keep the arena alive when humans are idle, and search for gaps automatically. This is real adversarial testing at $0.
**Priority:** SHOULD · **Lane:** AI · **Checkpoint:** IC3 · **Depends on:** F07 (Ollama), F15, F21 (templates)

## Provides
A background worker that plays the arena as "Red Agent", plus start, stop and status controls in the console.

## Behavior

**Loop:**
1. Pick a seed: an instantiated attack template (F21), a hand-tuned attack, or a previous near-miss (an attempt where Guard needed approval or was ambiguous).
2. Pick a mutation strategy with a simple bandit: 80% the best success rate so far against Guard and Full, 20% random.
3. Ask the **Ollama model** to rewrite the seed with that strategy, using a fixed instruction per strategy.
4. Validate the result like a player's payload (length, no null bytes). Submit it through the normal arena path at the lowest priority.
5. Record the outcome and update the strategy weights.

**Strategies:**
- Paraphrase.
- Authority framing.
- Fake system message.
- Language switch.
- Base64 encoding.
- Split across two records (plants two payloads).
- Hide in an HTML or markdown comment.
- Customer roleplay.
- Exploit ambiguity (reuse a value that also appears in trusted data).
- Link smuggling (wrap a URL in friendly text).

**Pacing:**
- At most 6 attempts per minute.
- Pause whenever human attempts are queued.
- Stop at economy mode if it was using Gemini.

**A breach it finds** is handled exactly like a human breach: the alarm, and an Autopilot proposal with trigger `red_agent_breach`. In autonomous mode, this is the "self-healing" loop.

## Edge cases
- Ollama is unavailable → the Red Agent idles with a visible status. It never silently falls back to paid models unless spend is under $6 and the toggle allows it.

## Performance budget
Throughput is set by Ollama on CPU. At least 1 attempt per 90 s is acceptable.

## Security notes
Its output is untrusted text, like any player's.

## Tests
| Test | Asserts |
|---|---|
| mutation stays within limits | |
| pauses when humans are queued | |
| bandit weights update | |
| never uses paid models over $6 | |

## Done when
It produces 20 varied attempts unattended, visible on the big screen with robot badges, at $0 Gemini spend.

## Fallback if cut
A replay bot that resubmits instantiated templates on a timer.

## Freedom
The bandit algorithm and the strategy prompts.
