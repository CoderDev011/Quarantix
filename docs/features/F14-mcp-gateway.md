# F14. MCP gateway with tool pinning ("live on stage")

**Purpose:** protect an **off-the-shelf agent we did not write**, with zero code changes, and stop the best-known MCP attack, the rug pull, deterministically and live.
**Priority:** SHOULD · **Lane:** Platform · **Checkpoint:** IC3 (H15) · **Depends on:** F03 (devops and code-hosting packs served as MCP servers), F11, F12, F13; spike S5

## Why this matters: the real-world example (read before building)

The **Model Context Protocol (MCP)** lets any agent app (Gemini CLI, desktop assistants, IDEs) plug in tool servers written by third parties. The agent reads each tool's **description** to decide how to use it. That description is text written by someone else, and the model reads it as instructions.

Invariant Labs published two attacks on this design on 2025-04-01 (source: `docs/incidents.md` I-2):
- **Tool poisoning:** "malicious instructions are embedded within MCP tool descriptions that are invisible to users" but visible to the model. A tool called "add numbers" can quietly tell the model to read the user's SSH key and pass it in a hidden argument.
- **Rug pull:** "a malicious server can change the tool description after the client has already approved it." You approve an honest tool on Monday; on Tuesday its description changes, and your agent obeys the new text without asking you again.

Invariant's own recommendation is exactly what we build: "Clients should pin the version of the MCP server and its tools… by using a hash or checksum to verify the integrity of the tool description before executing it."

A second Invariant report (2025-05-26, I-3) showed a malicious **public GitHub issue** hijacking an agent through the official GitHub MCP server, so that it copied private-repository data into a public pull request. Our code-hosting replay (RW-02) recreates this against fake repositories, and AgentWall's C2 rule blocks it.

**Why AgentWall's answer is stronger than a warning dialog:**
1. Pinning is enforced in the gateway, so it works with **any** client, including ones that never ask.
2. Even a poisoned description cannot make a secret flow to an external audience: C2 blocks it on the data, not on the wording.
3. Unknown tools are default deny.

## Provides
- A **gateway process** that is an MCP server to the client and an MCP client to one or more upstream MCP servers.
  - Transports: stdio (desktop and CLI clients start it themselves) and streamable HTTP on port 8788.
- A **pin store** (contracts §15), plus admin endpoints to list pins, show the description diff, and approve or reject.
- **Description scanning:** warnings only.

## Behavior

**Start-up:**
1. Connect to the configured upstreams.
2. List their tools.
3. For each tool:

| State | Status | Behavior |
|---|---|---|
| Configured in the gateway config, first seen | **pinned** | Hash the description and schema and store them |
| Not configured | **new_pending** | Hidden from the client until approved; default-deny labels even after approval unless configured |
| Already pinned, hash matches | pinned | Mirror it |
| Already pinned, hash differs | **changed_pending** | Hidden from the client, all calls blocked with `runtime/mcp-tool-unpinned`. Emits `mcp.tool_changed` with the diff |

4. Mirror the pinned tools to the client, with the same names, descriptions and schemas.

**Re-listing:**
- Re-list upstream tools every 10 s, or on the upstream's list-changed notification.
- When the set of visible tools changes, notify the client (MCP list-changed), so a hidden tool disappears from the client's UI **live**.

**Calls:**
- Each client connection gets one guard session (F11). Labels come from the gateway config, which uses the same fields as a tool spec.
- Upstream results are labeled and indexed as in guard mode.

**Description scan** (warnings only):
- Flag imperative instructions to the model ("ignore previous", "before using this tool, read…", "do not tell the user"), hidden characters, very long descriptions, and requests for files or keys.
- Emits `mcp.description_flagged`.

**Events and policy** flow through the SDK transport (F12), so the console and Autopilot see MCP traffic like any agent.

**Stage client:**
- Spike S5 decides it.
- Preferred: **Gemini CLI** configured to start the gateway over stdio. It uses its own Google sign-in quota, not our $12.
- Guaranteed fallback: **MCP Inspector**.

**The rug-pull demo control:**
- The devops MCP tool server has an admin switch (console button "Simulate rug pull"). It swaps `read_logs`' description to a poisoned version that tells the model to call `run_shell` with the attacker's curl command.
- The tool then disappears from the client within 10 s, and the console shows the diff with Approve/Reject buttons.

## Edge cases
- The upstream is down → its tools are hidden, with a clear status in the console.
- Two upstreams expose the same tool name → prefix with the server name.
- The client calls a hidden tool by name → blocked with a clear error message.

## Performance budget
- Gateway overhead per call: under 5 ms (excluding upstream time).
- Hash and diff on re-list: under 10 ms for 50 tools.

## Security notes
- The gateway never forwards a call to a tool whose current hash differs from the pinned one, even for a single request in a race. Check the hash on every call, not only on re-list.

## Tests
| Test | Asserts |
|---|---|
| mirrored tools match upstream | |
| blocked call never reaches upstream | HTTP mocked, zero upstream calls |
| changed description → hidden and blocked until approved | |
| race: description changes between list and call → blocked | |
| unknown tool default deny | |
| poisoned log through the gateway → C1 block | |
| private file into a public pull request → C2 block | code-hosting |
| description scan flags a poisoned description | |

## Done when
- **On stage:** the off-the-shelf client lists the mirrored tools and does the benign task. "Simulate rug pull" makes the tool vanish from the client, and the console shows the diff.
- **Bonus:** if spike S5 showed that the client takes the bait, the poisoned-log injection is blocked by C1 with the provenance graph.

## Fallback if cut
The SDK-guarded devops agent stands in for "an agent we didn't build", and the rug pull is explained on a slide.

## Freedom
Gateway internals, re-list strategy and diff rendering.
