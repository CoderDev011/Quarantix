"""The drop-in (F12 "done when"): an agent we did not write, protected by a few SDK lines.

    QX_API=http://127.0.0.1:8000 QX_AGENT_KEY=<key> \\
        uv run python scripts/guarded_agent.py support            # benign run
    ... scripts/guarded_agent.py support --plant "<ticket text>"  # with a planted record

The naive agent and its tools are unchanged. The only AgentWall code is marked
"AgentWall" below: create the SDK, wrap the tools, open a session. Decisions are
made locally, so stopping the control plane still blocks attacks (events are
buffered and delivered when it comes back).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quarantix.ai.llm import ToolCall, ToolResult  # noqa: E402
from quarantix.ai.naive_agent import NaiveAgent, tool_defs  # noqa: E402
from quarantix.api.runtime import build_models  # noqa: E402
from quarantix.packs.loader import load_domain  # noqa: E402
from quarantix.sdk import Quarantix  # noqa: E402


def own_tools(world: Any) -> list[Any]:
    """The agent's existing tool functions (here: a fake domain's)."""
    return [fn for n in world.registry.names() if (fn := world.registry.get(n).fn)]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", choices=["support", "devops"])
    parser.add_argument("--plant", default=None, help="text planted at the task's plant target")
    args = parser.parse_args()

    domain = load_domain(ROOT / "domains" / args.domain)
    world = domain.world()
    task = next(iter(domain.tasks.values()))
    if args.plant:
        t = task.plant
        world.plant(t.store, "new", t.field, args.plant, new_id=t.new_id, defaults=t.defaults)
    models = build_models()
    brains = models.brains()

    # ---- AgentWall: three lines -------------------------------------------------------
    url = os.environ.get("QX_API", "http://127.0.0.1:8000")
    qx = Quarantix(
        api_key=os.environ["QX_AGENT_KEY"], agent=domain.agent, url=url, registry=world.registry
    )
    tools = {fn.__name__: fn for fn in qx.wrap(own_tools(world))}
    # -----------------------------------------------------------------------------------

    async def invoke(call: ToolCall) -> ToolResult:  # the agent's own tool runner, unchanged
        return ToolResult(call.id, call.name, await tools[call.name](**call.arguments))

    agent = NaiveAgent(brains.naive_llm, brains.naive_model, tool_defs(world.registry), invoke,
                       system_prompt=domain.system_prompt)  # fmt: skip
    async with qx, qx.session(task.request):  # AgentWall: one guard session per task
        result = await agent.run(task.request)
    await models.close()

    print(f"answer: {result.answer!r} (stop: {result.stop})")
    for name, rows in world.snapshot().items():
        print(f"ledger {name}: {rows}")
    blocked = [r for m in result.transcript for r in m.tool_results if r.is_error]
    print(f"blocked or failed calls: {len(blocked)}")
    print(f"SDK status: {qx.status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
