"""A deterministic stand-in for the quarantined reader: honest, keyword-based extraction.

It keeps the reader's labeling contract (every field carries the source's label),
so the engine sees exactly what it would see with the real reader.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from quarantix.core.labels import Labeled
from quarantix.core.provenance import ProvenanceGraph

WANTS = ("refund", "money back")


def read_field(text: str, ftype: str) -> Any:
    lowered = text.lower()
    if ftype == "bool":
        return any(word in lowered for word in WANTS)
    if ftype.startswith("pattern:"):
        pattern = ftype[len("pattern:") :].removeprefix("^").removesuffix("$")
        match = re.search(pattern, text)
        return match.group(0) if match else None
    if ftype.startswith("enum:"):
        options = ftype[len("enum:") :].split("|")
        found = [
            (m.start(), o) for o in options for m in re.finditer(rf"\b{re.escape(o)}\b", lowered)
        ]
        return min(found)[1] if found else None
    if ftype.startswith(("money", "number")):
        match = re.search(r"\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None
    return None


class HonestReader:
    def __init__(self) -> None:
        self.calls = 0

    async def extract(
        self, source: Labeled, fields: Mapping[str, str], graph: ProvenanceGraph, step_id: str
    ) -> Labeled:
        self.calls += 1
        text = str(source.plain())
        out = {
            name: Labeled(
                read_field(text, ftype),
                source.label,
                graph.add("extract", f"{step_id}.{name}", source.label, [source.node]),
            )
            for name, ftype in fields.items()
        }
        node = graph.add("extract", step_id, source.label, [source.node])
        return Labeled(out, source.label, node)
