# F01. Labels and provenance

**Purpose:** the vocabulary of trust and sensitivity, plus a record of how every value was produced. Every other feature builds on it.
**Priority:** MUST · **Lane:** Engine · **Checkpoint:** IC1 (H6) · **Depends on:** contracts §1, §2, §6

## Provides
- An immutable **label** with a join operation, a bottom label, and helpers to build trusted or untrusted labels from a source name. Confidentiality defaults to internal.
- **Join-all:** combines any number of labels; empty input gives bottom.
- A **labeled value** with field access (child label joined with the container's) and conversion to a plain value.
- Conversion of labels to and from the contract's wire format.
- A **provenance graph** per run or session:
  - Add a node (kind, title, label, parents) and get back a short id.
  - Ask for a node's **explanation**: its ancestors as nodes plus edges, at most 50 nodes, in the wire format of contracts §6.

## Behavior
- Integrity and confidentiality are ordered enums, so join is "max, max, union". Labels are immutable and hashable, so they can be cache keys.
- **Explanation:**
  - Walk ancestors breadth-first from the node.
  - When over 50, keep the nearest nodes **and always keep every root** (nodes with no parents: user, planner, tool results), so the UI can show where data came from.
  - Edges are only between kept nodes, plus a synthetic edge from a kept node to each root that was cut off from it.
- The graph is append-only; node ids are sequential within a graph.

## Edge cases
- A join over hundreds of labels in a loop stays fast (sources are a set; avoid copying when the result equals one input).
- A container with no fields still has its own label.
- Cycles are impossible, because parents must already exist. Reject unknown parent ids.

## Performance budget
- Join: under 1 µs typical.
- An explanation over a 5,000-node graph: under 2 ms.

## Security notes
- Labels must not be mutable after creation. A label that changes after a check is a bypass.

## Tests
| Test | Asserts |
|---|---|
| join laws (property-based) | Commutative, associative, idempotent; bottom is the identity, over all enum combinations and random source sets |
| one untrusted taints | Joining any list containing one untrusted label gives untrusted |
| field access joins | Trusted container + untrusted child → untrusted; untrusted container + trusted child → untrusted |
| explanation completeness | Below the cap, the explanation contains every ancestor and only ancestors |
| explanation cap keeps roots | A deep 200-node chain explained at cap 50 still includes the root |
| unknown parent rejected | Adding a node with an unknown parent fails |
| wire round trip | Label → wire → label is identical |

## Done when
All tests pass in CI, and F04, F05 and F06 use these types without wrappers.

## Fallback if cut
None; this is foundational.

## Freedom
The representation is free: interned source sets or bitsets for common sources, for example, as long as the wire format matches the contract.
