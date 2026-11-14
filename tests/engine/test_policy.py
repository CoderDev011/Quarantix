"""F04 core rules and the combine order. Spec: docs/features/F04-policy-engine.md."""

import time

import pytest

from agentwall.core.labels import Confidentiality, untrusted
from agentwall.core.registry import Registry
from agentwall.engine.policy import evaluate
from tests.engine._factories import (
    PAY_PACK,
    arg,
    pay_spec,
    policy,
    post_spec,
    read_spec,
    request,
)

TAINTED = untrusted("tool:read#R-102")

# ---------------------------------------------------------------- C1


@pytest.mark.parametrize("evidence", ["exact", "traced"])
def test_c1_blocks_an_untrusted_critical_argument(evidence: str) -> None:
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(4999, bad=True, evidence=evidence)),  # type: ignore[arg-type]
        pay_spec(),
        policy(),
    )
    assert (decision.kind, decision.rule) == ("block", "core/C1-untrusted-critical-arg")
    assert decision.offending_arg == "amount"


def test_c1_asks_when_the_trace_is_ambiguous() -> None:
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(120, bad=True, evidence="ambiguous")),
        pay_spec(),
        policy(),
    )
    assert (decision.kind, decision.rule) == ("ask", "core/C1-untrusted-critical-arg")


def test_inferred_taint_asks_via_c3_and_never_blocks() -> None:
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(120, bad=True, evidence="inferred")),
        pay_spec(),
        policy(),
    )
    assert (decision.kind, decision.rule) == ("ask", "core/C3-untrusted-context-high-risk")


def test_untrusted_non_critical_argument_is_allowed() -> None:
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(10), note=arg("hi", bad=True)),
        pay_spec(),
        policy(),
    )
    assert decision.kind == "allow"


# ---------------------------------------------------------------- C2


def test_c2_blocks_private_data_sent_to_an_external_audience() -> None:
    decision = evaluate(
        request(
            "post",
            channel=arg("https://hooks.example.org/x"),
            text=arg("secret plan", conf=Confidentiality.PRIVATE, source="tool:read#R-9"),
        ),
        post_spec(),
        policy(),
    )
    assert (decision.kind, decision.rule) == ("block", "core/C2-confidentiality-exceeds-audience")
    assert decision.offending_arg == "text"


def test_c2_allows_private_data_sent_to_an_internal_audience() -> None:
    decision = evaluate(
        request(
            "post", channel=arg("#team-log"), text=arg("summary", conf=Confidentiality.PRIVATE)
        ),
        post_spec(),
        policy(),
    )
    assert decision.kind == "allow"


# ---------------------------------------------------------------- C3


def test_c3_asks_for_high_risk_calls_in_an_untrusted_context() -> None:
    decision = evaluate(
        request("pay", context=TAINTED, account=arg("ACC-1"), amount=arg(10)),
        pay_spec(),
        policy(),
    )
    assert (decision.kind, decision.rule) == ("ask", "core/C3-untrusted-context-high-risk")


def test_c3_ignores_medium_risk_calls() -> None:
    decision = evaluate(
        request("post", context=TAINTED, channel=arg("#team-log"), text=arg("ok")),
        post_spec(),
        policy(),
    )
    assert decision.kind == "allow"


# ---------------------------------------------------------------- combine order


def test_a_named_allow_relaxes_a_core_ask() -> None:
    decision = evaluate(
        request("pay", context=TAINTED, account=arg("ACC-1"), amount=arg(120)),
        pay_spec(),
        policy(PAY_PACK),
    )
    assert (decision.kind, decision.rule) == ("allow", "money/small-trusted-payments")


def test_a_named_allow_relaxes_only_when_its_conditions_hold() -> None:
    decision = evaluate(
        request("pay", context=TAINTED, account=arg("ACC-1"), amount=arg(5000)),
        pay_spec(),
        policy(PAY_PACK),
    )
    assert decision.kind == "ask"


@pytest.mark.parametrize("pack_decision", ["allow", "ask"])
def test_nothing_relaxes_a_core_block(pack_decision: str) -> None:
    pack = f"""\
schema_version: 1
pack: lenient
rules:
  - name: anything-goes
    tool: pay
    decision: {pack_decision}
"""
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(4999, bad=True)),
        pay_spec(),
        policy(pack),
    )
    assert (decision.kind, decision.rule) == ("block", "core/C1-untrusted-critical-arg")


def test_a_pack_block_beats_a_core_ask() -> None:
    pack = """\
schema_version: 1
pack: strict
rules:
  - name: no-payments-from-untrusted-context
    tool: pay
    when: [{context: {integrity: untrusted}}]
    decision: block
    reason: Payments never run after reading untrusted content
"""
    decision = evaluate(
        request("pay", context=TAINTED, account=arg("ACC-1"), amount=arg(10)),
        pay_spec(),
        policy(PAY_PACK, pack),
    )
    assert (decision.kind, decision.rule) == ("block", "strict/no-payments-from-untrusted-context")
    assert decision.reason == "Payments never run after reading untrusted content"


def test_a_pack_ask_applies_when_the_core_allows() -> None:
    pack = """\
schema_version: 1
pack: careful
rules:
  - name: big-payments-need-a-human
    tool: pay
    when: [{arg: amount, value: {gt: 2000}}]
    decision: ask
"""
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(2001)), pay_spec(), policy(pack)
    )
    assert (decision.kind, decision.rule) == ("ask", "careful/big-payments-need-a-human")


def test_source_tools_are_never_checked() -> None:
    decision = evaluate(
        request("read", context=TAINTED, id=arg("x", bad=True)), read_spec(), policy()
    )
    assert decision.kind == "allow"


def test_unregistered_tools_block_any_untrusted_argument() -> None:
    spec = Registry().get("mystery")
    decision = evaluate(request("mystery", anything=arg("x", bad=True)), spec, policy())
    assert (decision.kind, decision.rule) == ("block", "core/C1-untrusted-critical-arg")


# ---------------------------------------------------------------- decision content


def test_reason_names_the_argument_and_its_source() -> None:
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(4999, bad=True, source="tool:read#R-102")),
        pay_spec(),
        policy(),
    )
    assert "amount" in decision.reason
    assert "R-102" in decision.reason


def test_matched_lists_every_rule_that_fired() -> None:
    decision = evaluate(
        request("pay", context=TAINTED, account=arg("ACC-1", bad=True), amount=arg(120, bad=True)),
        pay_spec(),
        policy(PAY_PACK),
    )
    assert "core/C1-untrusted-critical-arg" in decision.matched
    assert "core/C3-untrusted-context-high-risk" in decision.matched


def test_decision_carries_the_bundle_version() -> None:
    agent_policy = policy(PAY_PACK)
    decision = evaluate(
        request("pay", account=arg("ACC-1"), amount=arg(1)), pay_spec(), agent_policy
    )
    assert decision.policy_version == agent_policy.version
    assert len(decision.policy_version) == 12


# ---------------------------------------------------------------- link operator

LINK_PACK = """\
schema_version: 1
pack: links
allowed_link_hosts: [company.example]
rules:
  - name: no-foreign-links-in-untrusted-text
    tool: post
    when: [{arg: text, integrity: not_trusted, value: {has_link_outside_allowed_hosts: true}}]
    decision: block
    reason: Untrusted text tried to put an outside link in an internal message
"""


def test_link_operator_blocks_a_foreign_link_in_untrusted_text() -> None:
    text = arg("Please re-verify at https://sso.attacker.test/reauth", bad=True)
    decision = evaluate(
        request("post", channel=arg("#team-log"), text=text), post_spec(), policy(LINK_PACK)
    )
    assert (decision.kind, decision.rule) == ("block", "links/no-foreign-links-in-untrusted-text")


def test_link_operator_allows_links_to_allowed_hosts() -> None:
    text = arg("Docs: https://www.company.example/help", bad=True)
    decision = evaluate(
        request("post", channel=arg("#team-log"), text=text), post_spec(), policy(LINK_PACK)
    )
    assert decision.kind == "allow"


# ---------------------------------------------------------------- performance


@pytest.mark.perf
def test_evaluation_p99_is_under_one_millisecond_with_100_rules() -> None:
    rules = "\n".join(
        f"  - name: rule-{i}\n    tool: pay\n"
        f"    when: [{{arg: amount, integrity: trusted, value: {{lte: {i}}}}}, "
        f"{{arg: note, value: {{regex: 'n[0-9]+'}}}}]\n    decision: ask"
        for i in range(100)
    )
    agent_policy = policy(f"schema_version: 1\npack: big\nrules:\n{rules}\n")
    call = request(
        "pay",
        context=TAINTED,
        account=arg("ACC-1"),
        amount=arg(5000),
        note=arg("n1"),
        a=arg(1),
        b=arg(2),
        c=arg(3),
    )
    spec = pay_spec()
    timings = []
    for _ in range(2000):
        start = time.perf_counter()
        evaluate(call, spec, agent_policy)
        timings.append(time.perf_counter() - start)
    p99 = sorted(timings)[int(len(timings) * 0.99)]
    print(f"\nevaluate p99 (100 rules, 6 args): {p99 * 1e6:.0f} µs")
    assert p99 < 1e-3
