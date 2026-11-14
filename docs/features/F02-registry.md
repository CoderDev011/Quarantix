# F02. Tool registry

**Purpose:** declare each tool's kind, risk, audience and labels once, so every way in (full mode, SDK, MCP gateway, arena) judges the same tool the same way.
**Priority:** MUST · **Lane:** Engine · **Checkpoint:** IC1 · **Depends on:** F01, contracts §3

## Provides
- A **registry** per agent:
  - Register a tool spec, either from a Python function (for SDK users wrapping their own tools) or from a domain-pack manifest entry (F03).
  - Look up by name. **An unknown name returns the default-deny spec** (contracts §3).
  - A **catalog**: name, description, argument schema and kind, sorted by name. The planner and the naive agent receive it.
  - A **version**: a stable hash.
- Audience resolution: given a spec and concrete arguments, return the audience (fixed, or computed by an audience rule from contracts §10.4, using a world lookup function that F03 provides).

## Behavior
- **Registering from a function:** the argument schema comes from type hints and defaults; the docstring becomes the description. Both sync and async functions are accepted; the runtime runs sync functions off the event loop.
- **Registering from a manifest:** the schema comes from the manifest's parameters.
- The version is the hash of the canonical, sorted catalog plus label metadata. It must not depend on registration order.
- Registering the same name twice is an error, unless the spec is identical (idempotent).

## Edge cases
- A tool with no parameters.
- A parameter typed as a union or optional.
- An audience rule whose record lookup fails → audience **external** (default deny).

## Performance budget
- Lookup is O(1).
- The catalog and version are computed once per change and cached.

## Security notes
- Default deny for unknown tools is the single most important property here. Test it explicitly.
- An audience-rule failure must never fall back to internal.

## Tests
| Test | Asserts |
|---|---|
| register and look up | Kind, risk and critical arguments are preserved |
| unknown is default deny | Sink, high, external, all arguments critical |
| schema from hints | A float argument appears as number; required versus optional is correct |
| version stability | Same tools in a different order → same version; a changed risk → different version |
| audience rule fallback | A failed record lookup → external |
| duplicate registration | An identical spec is accepted; a different spec is rejected |

## Done when
Both MUST domain packs (F03) register all their tools through the manifest path with no core changes, and the SDK can register a plain Python function.

## Freedom
Whether specs are stored as dataclasses or models, and how the schema is generated.
