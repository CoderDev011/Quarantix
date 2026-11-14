"""F01 provenance graph. Spec: docs/features/F01-labels-provenance.md, contracts section 6."""

import time

import pytest

from quarantix.core.labels import trusted, untrusted
from quarantix.core.provenance import ProvenanceGraph


def _ids(explanation: dict) -> set[str]:
    return {node["id"] for node in explanation["nodes"]}


def _edges(explanation: dict) -> set[tuple[str, str]]:
    return {(edge["source"], edge["target"]) for edge in explanation["edges"]}


def test_node_ids_are_sequential() -> None:
    graph = ProvenanceGraph()
    assert graph.add("user", "request", trusted("user")) == "n1"
    assert graph.add("planner", "plan", trusted("planner")) == "n2"


def test_unknown_parent_is_rejected() -> None:
    graph = ProvenanceGraph()
    with pytest.raises(ValueError, match="n9"):
        graph.add("tool", "list", untrusted("tool:list#1"), parents=["n9"])


def test_unknown_kind_is_rejected() -> None:
    graph = ProvenanceGraph()
    with pytest.raises(ValueError, match="kind"):
        graph.add("banana", "x", trusted("user"))


def test_explanation_contains_exactly_the_ancestors() -> None:
    graph = ProvenanceGraph()
    user = graph.add("user", "request", trusted("user"))
    tool = graph.add("tool", "list", untrusted("tool:list#1"))
    sibling = graph.add("tool", "other", untrusted("tool:get#2"))
    extract = graph.add("extract", "amount", untrusted("tool:list#1"), parents=[tool])
    arg = graph.add("arg", "amount", untrusted("tool:list#1"), parents=[extract, user])

    explanation = graph.explain(arg)

    assert _ids(explanation) == {user, tool, extract, arg}
    assert sibling not in _ids(explanation)
    assert _edges(explanation) == {(tool, extract), (extract, arg), (user, arg)}


def test_explanation_nodes_use_the_wire_format() -> None:
    graph = ProvenanceGraph()
    node = graph.add("tool", "list", untrusted("tool:list#1"))
    assert graph.explain(node)["nodes"] == [
        {
            "id": node,
            "kind": "tool",
            "title": "list",
            "label": {
                "integrity": "untrusted",
                "confidentiality": "internal",
                "sources": ["tool:list#1"],
            },
        }
    ]


def test_capped_explanation_keeps_the_root() -> None:
    graph = ProvenanceGraph()
    root = graph.add("tool", "list", untrusted("tool:list#1"))
    last = root
    for i in range(199):
        last = graph.add("format", f"step {i}", untrusted("tool:list#1"), parents=[last])

    explanation = graph.explain(last, limit=50)
    ids = _ids(explanation)

    assert len(ids) == 50
    assert {root, last} <= ids
    # The root was cut off from the kept chain, so a synthetic edge reconnects it.
    targets_of_root = {target for source, target in _edges(explanation) if source == root}
    assert len(targets_of_root) == 1
    assert targets_of_root <= ids


def test_cap_holds_even_with_more_roots_than_the_limit() -> None:
    graph = ProvenanceGraph()
    roots = [graph.add("tool", f"src {i}", untrusted(f"tool:get#{i}")) for i in range(60)]
    sink = graph.add("sink", "send", untrusted("tool:get#0"), parents=roots)

    explanation = graph.explain(sink, limit=50)

    assert len(explanation["nodes"]) == 50
    assert sink in _ids(explanation)


def test_adding_nodes_never_changes_an_earlier_explanation() -> None:
    graph = ProvenanceGraph()
    tool = graph.add("tool", "list", untrusted("tool:list#1"))
    before = graph.explain(tool)
    graph.add("extract", "x", untrusted("tool:list#1"), parents=[tool])
    assert graph.explain(tool) == before


@pytest.mark.perf
def test_explaining_a_5000_node_graph_is_under_2ms() -> None:
    graph = ProvenanceGraph()
    previous = [graph.add("tool", "root", untrusted("tool:list#1"))]
    for i in range(4999):
        parents = previous[-2:]
        previous.append(graph.add("format", f"n{i}", untrusted("tool:list#1"), parents=parents))

    start = time.perf_counter()
    graph.explain(previous[-1])
    elapsed = time.perf_counter() - start
    print(f"\nexplain over 5000 nodes: {elapsed * 1e3:.2f} ms")
    assert elapsed < 2e-3
