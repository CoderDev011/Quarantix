"""Re-decide stored decisions under a candidate bundle (F18 proof step 3).

Stored events keep only previews (scrubbed, at most 40 characters), the labels
and the evidence. A decision that changes when its value was cut or redacted
cannot be judged honestly from the preview, so it counts as "unknown".
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from quarantix.core.contracts import ArgValue, Event, ToolCallRequest
from quarantix.core.labels import BOTTOM, Label
from quarantix.core.registry import Registry
from quarantix.engine.policy import PolicyBundle, evaluate


def _value(preview: dict[str, Any]) -> tuple[Any, bool]:
    shown = preview.get("preview")
    exact = not preview.get("redacted") and not (isinstance(shown, str) and shown.endswith("…"))
    if isinstance(shown, str):
        try:
            return float(shown), exact
        except ValueError:
            return shown, exact
    return shown, exact


def redecide(
    events: Iterable[Event],
    registry: Registry,
    before: PolicyBundle,
    after: PolicyBundle,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    checked = flipped = unknown = 0
    tightened = loosened = 0
    examples: list[dict[str, Any]] = []
    for event in events:
        if checked >= limit:
            break
        if event.kind != "tool.call" or event.tool is None or event.decision is None:
            continue
        args: dict[str, ArgValue] = {}
        exact_all = True
        for name, preview in (event.args or {}).items():
            value, exact = _value(dict(preview))
            exact_all = exact_all and exact
            try:
                label = Label.from_wire(preview["label"])
            except (KeyError, ValueError):
                label = BOTTOM
            evidence = preview.get("evidence", "inferred")
            args[name] = ArgValue(value, label, evidence if evidence in (
                "exact", "traced", "ambiguous", "inferred") else "inferred")  # fmt: skip
        request = ToolCallRequest(
            run_id=event.run_id, agent=event.agent, mode=event.mode, tool=event.tool,
            args=args, context=event.context or BOTTOM,
        )  # fmt: skip
        spec = registry.get(event.tool)
        old = evaluate(request, spec, before.for_agent(event.agent)).kind
        new = evaluate(request, spec, after.for_agent(event.agent)).kind
        checked += 1
        if old == new:
            continue
        if not exact_all:
            unknown += 1
            continue
        flipped += 1
        order = {"allow": 0, "ask": 1, "block": 2}
        if order[new] > order[old]:
            tightened += 1
        else:
            loosened += 1
        if len(examples) < 5:
            examples.append({"tool": event.tool, "run_id": event.run_id, "from": old, "to": new})
    return {
        "checked": checked,
        "flipped": flipped,
        "tightened": tightened,
        "loosened": loosened,
        "unknown": unknown,
        "examples": examples,
    }
