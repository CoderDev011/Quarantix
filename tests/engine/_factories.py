"""Small builders shared by the engine tests. Generic names only (no domain words)."""

from typing import Any

from quarantix.core.contracts import ArgValue, Evidence, ToolCallRequest
from quarantix.core.labels import BOTTOM, Confidentiality, Label, trusted, untrusted
from quarantix.core.registry import ChannelAllowlist, ToolSpec
from quarantix.engine.policy import AgentPolicy, PolicyBundle, compile_pack

AGENT = "agent-a"


def pay_spec() -> ToolSpec:
    return ToolSpec(
        name="pay",
        kind="sink",
        description="Move money.",
        arg_schema={
            "type": "object",
            "properties": {
                "account": {"type": "string"},
                "amount": {"type": "number"},
                "note": {"type": "string"},
            },
        },
        risk="high",
        audience="internal",
        critical_args=("account", "amount"),
    )


def post_spec() -> ToolSpec:
    return ToolSpec(
        name="post",
        kind="sink",
        description="Post a message.",
        arg_schema={
            "type": "object",
            "properties": {"channel": {"type": "string"}, "text": {"type": "string"}},
        },
        risk="medium",
        audience=ChannelAllowlist(param="channel", known=frozenset({"#team-log"})),
        critical_args=("channel",),
    )


def read_spec() -> ToolSpec:
    return ToolSpec(
        name="read",
        kind="source",
        description="Read records.",
        arg_schema={"type": "object", "properties": {"id": {"type": "string"}}},
    )


def arg(
    value: Any,
    *,
    bad: bool = False,
    evidence: Evidence = "exact",
    source: str | None = None,
    conf: Confidentiality = Confidentiality.INTERNAL,
) -> ArgValue:
    """A labeled argument. `bad=True` means untrusted (attacker-writable)."""
    make = untrusted if bad else trusted
    return ArgValue(value, make(source or ("tool:read#R-102" if bad else "user"), conf), evidence)


def request(tool: str, context: Label = BOTTOM, **args: ArgValue) -> ToolCallRequest:
    return ToolCallRequest(
        run_id="run-1", agent=AGENT, mode="guard", tool=tool, args=args, context=context
    )


def policy(*pack_yaml: str) -> AgentPolicy:
    return PolicyBundle(tuple(compile_pack(text) for text in pack_yaml)).for_agent(AGENT)


PAY_PACK = """\
schema_version: 1
pack: money
applies_to: ["*"]
allowed_link_hosts: [company.example]
rules:
  - name: small-trusted-payments
    tool: pay
    when:
      - {arg: amount, integrity: trusted, value: {lte: 2000}}
      - {arg: account, integrity: trusted}
    decision: allow
    reason: Trusted payment under the limit
"""
