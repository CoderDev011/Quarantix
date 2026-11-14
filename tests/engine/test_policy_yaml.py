"""F04 pack compiler and bundle. Spec: docs/features/F04-policy-engine.md, contracts section 9."""

import contextlib
import gc
import json
import statistics
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentwall.engine.policy import Pack, PolicyBundle, PolicyError, compile_pack
from tests.engine._factories import PAY_PACK


def test_a_valid_pack_compiles() -> None:
    pack = compile_pack(PAY_PACK)
    assert pack.name == "money"
    assert [rule.name for rule in pack.rules] == ["small-trusted-payments"]
    assert pack.allowed_link_hosts == frozenset({"company.example"})


def test_a_bad_operator_reports_its_line() -> None:
    text = """\
schema_version: 1
pack: broken
rules:
  - name: r
    tool: pay
    when:
      - {arg: amount, value: {about: 5}}
    decision: ask
"""
    with pytest.raises(PolicyError) as error:
        compile_pack(text)
    assert error.value.line == 7
    assert "about" in str(error.value)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("schema_version: 1\npack: p\ncolour: red\nrules: []\n", "colour"),
        ("schema_version: 2\npack: p\nrules: []\n", "schema_version"),
        ("schema_version: 1\nrules: []\n", "pack"),
        (
            "schema_version: 1\npack: p\nrules:\n  - {name: r, tool: '*', decision: allow}\n",
            "wildcard",
        ),
        (
            "schema_version: 1\npack: p\nrules:\n"
            "  - {name: r, tool: pay, decision: ask}\n  - {name: r, tool: pay, decision: ask}\n",
            "duplicate",
        ),
        (
            "schema_version: 1\npack: p\nrules:\n  - {name: r, tool: pay, decision: maybe}\n",
            "maybe",
        ),
        (
            "schema_version: 1\npack: p\nrules:\n"
            "  - {name: r, tool: pay, decision: ask, when: [{shade: dark}]}\n",
            "shade",
        ),
        (
            "schema_version: 1\npack: p\nrules:\n"
            "  - {name: r, tool: pay, decision: ask, when: [{integrity: trusted}]}\n",
            "arg",
        ),
        ("schema_version: 1\npack: p\nmodes: {agent-a: loud}\nrules: []\n", "loud"),
        ("", "empty"),
        ("pack: [unclosed\n", "line"),
    ],
)
def test_invalid_packs_are_rejected_with_a_clear_message(text: str, fragment: str) -> None:
    with pytest.raises(PolicyError) as error:
        compile_pack(text)
    assert fragment in str(error.value)


@settings(max_examples=1000, deadline=None)
@given(st.text(max_size=300))
def test_fuzzed_text_never_crashes_the_compiler(text: str) -> None:
    try:
        result = compile_pack(text)
    except PolicyError:
        return
    assert isinstance(result, Pack)


@settings(max_examples=300, deadline=None)
@given(
    st.recursive(
        st.none() | st.booleans() | st.integers() | st.text(max_size=8),
        lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner),
        max_leaves=12,
    )
)
def test_fuzzed_structures_never_crash_the_compiler(rules: object) -> None:
    text = f"schema_version: 1\npack: p\nrules: {json.dumps(rules)}\n"
    with contextlib.suppress(PolicyError):
        compile_pack(text)


# ---------------------------------------------------------------- bundle


def test_bundle_version_is_stable_for_the_same_content() -> None:
    first = PolicyBundle((compile_pack(PAY_PACK),))
    second = PolicyBundle((compile_pack(PAY_PACK),))
    assert first.version == second.version
    assert len(first.version) == 12


def test_bundle_version_changes_on_any_edit() -> None:
    edited = PAY_PACK.replace("lte: 2000", "lte: 2001")
    assert (
        PolicyBundle((compile_pack(PAY_PACK),)).version
        != PolicyBundle((compile_pack(edited),)).version
    )


def test_bundle_version_ignores_pack_order() -> None:
    other = "schema_version: 1\npack: other\nrules: []\n"
    a, b = compile_pack(PAY_PACK), compile_pack(other)
    assert PolicyBundle((a, b)).version == PolicyBundle((b, a)).version


def test_agent_view_uses_only_packs_that_apply_to_it() -> None:
    only_b = (
        "schema_version: 1\npack: for-b\napplies_to: [agent-b]\n"
        "allowed_link_hosts: [b.example]\nrules: []\n"
    )
    bundle = PolicyBundle((compile_pack(PAY_PACK), compile_pack(only_b)))
    assert bundle.for_agent("agent-a").allowed_link_hosts == frozenset({"company.example"})
    assert bundle.for_agent("agent-b").allowed_link_hosts == frozenset(
        {"company.example", "b.example"}
    )


def test_agent_mode_defaults_to_enforce_and_can_be_set() -> None:
    monitored = "schema_version: 1\npack: m\nmodes: {agent-a: monitor}\nrules: []\n"
    bundle = PolicyBundle((compile_pack(monitored),))
    assert bundle.for_agent("agent-a").mode == "monitor"
    assert bundle.for_agent("agent-z").mode == "enforce"


@pytest.mark.parametrize("mode", ["off", "monitor", "enforce", "'off'"])
def test_unquoted_off_is_a_mode_not_a_yaml_boolean(mode: str) -> None:
    pack = compile_pack(f"schema_version: 1\npack: m\nmodes: {{agent-a: {mode}}}\nrules: []\n")
    assert pack.modes["agent-a"] == mode.strip("'")


def test_agent_view_is_memoized() -> None:
    bundle = PolicyBundle((compile_pack(PAY_PACK),))
    assert bundle.for_agent("agent-a") is bundle.for_agent("agent-a")


@pytest.mark.perf
def test_compiling_a_100_rule_pack_is_under_20ms() -> None:
    rules = "\n".join(
        f"  - name: rule-{i}\n    tool: pay\n"
        f"    when: [{{arg: amount, integrity: trusted, value: {{lte: {i}}}}}]\n"
        f"    decision: ask"
        for i in range(100)
    )
    text = f"schema_version: 1\npack: big\nrules:\n{rules}\n"
    gc.collect()  # don't charge a pause caused by earlier tests to this measurement
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        compile_pack(text)
        timings.append(time.perf_counter() - start)
    median = statistics.median(timings)
    runs = ", ".join(f"{t * 1e3:.1f}" for t in timings)
    print(f"\ncompile 100-rule pack: median {median * 1e3:.1f} ms (runs: {runs} ms)")
    assert median < 20e-3
