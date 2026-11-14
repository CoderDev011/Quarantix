"""Provenance graph: how each value was produced (F01, contracts section 6).

One graph per run or session. Nodes are append-only and can only point to
earlier nodes, so cycles are impossible. `explain` returns a node's ancestors in
the wire format, capped at `limit` nodes, always keeping the root origins so a
UI can show where the data came from.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agentwall.core.labels import Label

NODE_KINDS = frozenset({"user", "planner", "tool", "extract", "format", "arg", "sink"})
DEFAULT_LIMIT = 50


@dataclass(frozen=True, slots=True)
class _Node:
    id: str
    kind: str
    title: str
    label: Label
    parents: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "label": self.label.to_wire(),
        }


class ProvenanceGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, _Node] = {}
        # Root origins each node descends from, computed once at add time so that
        # explain() never has to walk the whole ancestry to find them.
        self._roots: dict[str, frozenset[str]] = {}

    def __len__(self) -> int:
        return len(self._nodes)

    def add(self, kind: str, title: str, label: Label, parents: Iterable[str] = ()) -> str:
        if kind not in NODE_KINDS:
            raise ValueError(f"unknown provenance node kind {kind!r}")
        parent_ids = tuple(dict.fromkeys(parents))  # de-duplicate, keep order
        for parent in parent_ids:
            if parent not in self._nodes:
                raise ValueError(f"unknown parent node {parent!r}")
        node_id = f"n{len(self._nodes) + 1}"
        self._nodes[node_id] = _Node(node_id, kind, title, label, parent_ids)
        self._roots[node_id] = self._roots_of_parents(parent_ids) or frozenset({node_id})
        return node_id

    def _roots_of_parents(self, parent_ids: tuple[str, ...]) -> frozenset[str]:
        if not parent_ids:
            return frozenset()
        first = self._roots[parent_ids[0]]
        rest = [self._roots[p] for p in parent_ids[1:] if self._roots[p] is not first]
        return first.union(*rest) if rest else first  # share the set when nothing new

    def explain(self, node_id: str, limit: int = DEFAULT_LIMIT) -> dict[str, list[dict[str, Any]]]:
        """Ancestors of `node_id` (including itself) as {"nodes": [...], "edges": [...]}.

        When there are more than `limit` ancestors, keep the node itself, then its
        root origins (newest first if even those exceed the limit), then the nearest
        other ancestors. A kept root whose real path was cut gets one synthetic edge
        to a kept descendant. Cost depends on `limit`, not on the size of the graph.
        """
        nodes = self._nodes
        if node_id not in nodes:
            raise KeyError(node_id)

        roots = sorted(self._roots[node_id] - {node_id}, key=_numeric_id, reverse=True)
        kept = {node_id, *roots[: limit - 1]}
        budget = limit - len(kept)  # slots left for non-root ancestors

        visited_order = [node_id]
        visited = {node_id}
        queue = deque([node_id])
        while queue and budget > 0:
            for parent in nodes[queue.popleft()].parents:
                if parent in visited:
                    continue
                visited.add(parent)
                visited_order.append(parent)
                if nodes[parent].parents:  # a non-root ancestor
                    if budget == 0:
                        break
                    kept.add(parent)
                    budget -= 1
                    queue.append(parent)

        ordered = [n for n in visited_order if n in kept]
        ordered += [r for r in roots if r in kept and r not in visited]

        edges: dict[tuple[str, str], None] = {}
        cut: list[tuple[str, str]] = []  # (dropped parent, kept descendant)
        for target in ordered:
            for parent in nodes[target].parents:
                if parent in kept:
                    edges[(parent, target)] = None
                else:
                    cut.append((parent, target))

        connected = {source for source, _ in edges}
        for dropped, descendant in cut:
            for root in self._roots[dropped]:
                if root in kept and root not in connected:
                    edges[(root, descendant)] = None
                    connected.add(root)

        return {
            "nodes": [nodes[n].to_wire() for n in ordered],
            "edges": [{"source": source, "target": target} for source, target in edges],
        }


def _numeric_id(node_id: str) -> int:
    return int(node_id[1:])
