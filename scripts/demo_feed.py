"""Send the IC1 demo's events to a running control plane, so the console has real data.

Runs the same two plans as scripts/demo_core.py (genuine refund ALLOWED, injected
refund BLOCKED by C1) and uploads every event with an agent key.
Usage (inside WSL, repo root, with the API running):
    QX_API=http://127.0.0.1:8765 QX_AGENT_KEY=<key> uv run python scripts/demo_feed.py
The key must belong to the agent "support-agent" (AGENTWALL_AGENT_KEYS).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_core import NAIVE_PLAN, SAFE_PLAN, ScriptedReader, build_world

from quarantix.core.contracts import Event
from quarantix.core.plan import parse_plan
from quarantix.engine.interpreter import RunContext, run_plan


class Collect:
    """Event sink that keeps events for one upload."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


async def main() -> int:
    base = os.environ.get("QX_API", "http://127.0.0.1:8000")
    key = os.environ.get("QX_AGENT_KEY")
    if not key:
        print("set QX_AGENT_KEY to the support-agent key", file=sys.stderr)
        return 2
    sink = Collect()
    registry, runtime = build_world(sink)  # type: ignore[arg-type]
    for run_id, plan in (("safe-run", SAFE_PLAN), ("naive-run", NAIVE_PLAN)):
        await run_plan(
            parse_plan(plan),
            registry=registry,
            runtime=runtime,
            reader=ScriptedReader(),
            ctx=RunContext(run_id=run_id, agent="support-agent"),
        )
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:
        response = await client.post(
            "/v1/events:batch",
            json={"events": [event.to_wire() for event in sink.events]},
            headers={"Authorization": f"Bearer {key}"},
        )
    print(response.status_code, response.json())
    return 0 if response.is_success and not response.json().get("rejected") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
