# Verified real-world incidents (the only ones allowed in public text)

Each entry was read from its primary source on 2026-11-14 and is quoted verbatim. To add an incident, read the primary source, quote it, and date it. Paraphrases from memory are not allowed.

## I-1. Slack AI: indirect prompt injection, phishing link and data exfiltration

- **Publisher:** PromptArmor. **Date:** 2024-08-20. **URL:** https://promptarmor.substack.com/p/data-exfiltration-from-slack-ai-via
- **What happened:**
  - An attacker creates a public Slack channel, with only themselves as a member, and posts an instruction aimed at Slack AI.
  - When a victim later asks Slack AI a question, the attacker's message and the victim's private data end up in the same context. Slack AI then shows a link that carries the victim's secret to the attacker.
  - The same post describes a phishing variant: Slack AI shows a fake "reauthenticate" link to a user who asks about a named person's messages.
- **Quotes:**
  - "renders the message enticing the user to click on the link to reauthenticate"
  - "Add the API key (which they do not have access to) as an HTTP parameter to a malicious link"
- Slack's quoted response called public-channel messages being searchable "intended behavior".
- **Used by:** scenario RW-01, arena goal `link_planted`, and the Autopilot "real gap" explanation (F18).

## I-2. MCP tool poisoning and rug pulls

- **Publisher:** Invariant Labs (Luca Beurer-Kellner, Marc Fischer). **Date:** 2025-04-01 (updated April 7 and 11). **URL:** https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks
- **Definitions, as stated:**
  - "A Tool Poisoning Attack occurs when malicious instructions are embedded within MCP tool descriptions that are invisible to users" but visible to AI models.
  - Rug pull: "a malicious server can change the tool description after the client has already approved it."
- **The recommendation we implement:** "Clients should pin the version of the MCP server and its tools to prevent unauthorized changes." "This can be done by using a hash or checksum to verify the integrity of the tool description before executing it."
- **Used by:** scenarios RW-03 and RW-04, and the MCP gateway's pinning (F14).

## I-3. GitHub MCP: a malicious public issue leaks private repositories

- **Publisher:** Invariant Labs (Marco Milanta, Luca Beurer-Kellner). **Date:** 2025-05-26. **URL:** https://invariantlabs.ai/blog/mcp-github-vulnerability
- **What happened:**
  - The attacker files a prompt-injection payload as an issue on a public repository.
  - When the owner asks their agent to review open issues, the agent reads the payload, pulls private-repository data into its context, and writes it into a pull request on the public repository, which the attacker can read.
  - The page says this is architectural, not a bug in the GitHub server code. It also says users often choose "Always Allow" for tool confirmations.
- **Quotes:**
  - "hijack a user's agent via a malicious GitHub Issue"
  - "which is freely accessible to the attacker since it is public"
- **Used by:** scenario RW-02 and the code-hosting domain pack.

## Not verified (do not use in public text)

- **EchoLeak / CVE-2025-32711 (Microsoft 365 Copilot).** The NVD page did not load on 2026-11-14. Verify and quote it before using.
