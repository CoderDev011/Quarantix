"""F10 naive baseline agent. Spec: docs/features/F10-naive-agent.md."""

import asyncio
import threading
from collections.abc import Sequence
from typing import Any

from quarantix.ai.llm import (
    JsonReply,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolDef,
    ToolResult,
    TurnReply,
    Usage,
)
from quarantix.ai.naive_agent import NaiveAgent, PlainInvoker, tool_defs
from quarantix.core.registry import Registry

TOOLS = [
    ToolDef(
        "lookup", "Look something up.", {"type": "object", "properties": {"q": {"type": "string"}}}
    ),
    ToolDef("other", "Another tool.", {"type": "object", "properties": {}}),
]


class ScriptedTurns:
    """Plays back assistant messages in order and remembers every history it was sent."""

    def __init__(self, replies: Sequence[Message | Exception]) -> None:
        self.replies = list(replies)
        self.histories: list[list[Message]] = []
        self.systems: list[str] = []

    async def json(self, **kwargs: Any) -> JsonReply:
        raise AssertionError("the naive agent only uses tool turns")

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        self.histories.append(list(messages))
        self.systems.append(system)
        reply = (
            self.replies.pop(0)
            if self.replies
            else Message("assistant", tool_calls=(ToolCall("loop", "lookup", {}),))
        )
        if isinstance(reply, Exception):
            raise reply
        return TurnReply(reply, Usage(100, 10), "stop")


def _calls(*names: str) -> Message:
    return Message(
        "assistant", tool_calls=tuple(ToolCall(f"c{i}", n, {}) for i, n in enumerate(names))
    )


class RecordingInvoker:
    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def __call__(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(call.id, call.name, {"ok": call.name})


async def test_an_immediate_answer_ends_the_run() -> None:
    llm = ScriptedTurns([Message("assistant", text="Nothing to do.")])
    result = await NaiveAgent(llm, "m", TOOLS, RecordingInvoker(), system_prompt="Be helpful.").run(
        "Hi"
    )
    assert (result.answer, result.turns, result.stop) == ("Nothing to do.", 1, "answered")
    assert llm.systems == [
        "Be helpful."
    ]  # the system prompt is passed unchanged, with no added defenses


async def test_all_tool_results_of_a_turn_go_back_in_one_message() -> None:
    llm = ScriptedTurns([_calls("lookup", "other"), Message("assistant", text="done")])
    invoker = RecordingInvoker()
    result = await NaiveAgent(llm, "m", TOOLS, invoker, system_prompt="s").run("go")
    second_history = llm.histories[1]
    tool_message = second_history[-1]
    assert tool_message.role == "tool"
    assert [r.name for r in tool_message.tool_results] == ["lookup", "other"]
    assert [c.name for c in result.tool_calls] == ["lookup", "other"]


async def test_tool_calls_in_one_turn_run_concurrently() -> None:
    started: list[str] = []
    both_started = asyncio.Event()

    async def invoker(call: ToolCall) -> ToolResult:
        started.append(call.name)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)  # would time out if run one by one
        return ToolResult(call.id, call.name, "ok")

    llm = ScriptedTurns([_calls("lookup", "other"), Message("assistant", text="done")])
    result = await NaiveAgent(llm, "m", TOOLS, invoker, system_prompt="s").run("go")
    assert result.stop == "answered"


async def test_a_failing_or_blocked_tool_becomes_an_error_result_and_the_agent_continues() -> None:
    async def invoker(call: ToolCall) -> ToolResult:
        raise RuntimeError("Blocked by security policy: the amount came from untrusted text")

    llm = ScriptedTurns([_calls("lookup"), Message("assistant", text="I could not do that.")])
    result = await NaiveAgent(llm, "m", TOOLS, invoker, system_prompt="s").run("go")
    (error,) = llm.histories[1][-1].tool_results
    assert error.is_error and "Blocked by security policy" in str(error.content)
    assert result.answer == "I could not do that."


async def test_unknown_tools_get_an_error_result_without_being_invoked() -> None:
    invoker = RecordingInvoker()
    llm = ScriptedTurns([_calls("teleport"), Message("assistant", text="ok")])
    await NaiveAgent(llm, "m", TOOLS, invoker, system_prompt="s").run("go")
    assert invoker.calls == []
    (error,) = llm.histories[1][-1].tool_results
    assert error.is_error and "teleport" in str(error.content)


async def test_the_turn_limit_stops_a_looping_model() -> None:
    llm = ScriptedTurns([])  # always asks for another tool call
    result = await NaiveAgent(
        llm, "m", TOOLS, RecordingInvoker(), system_prompt="s", max_turns=3
    ).run("go")
    assert (result.turns, result.stop, result.answer) == (3, "turn_limit", None)


async def test_a_model_outage_ends_the_run_honestly() -> None:
    llm = ScriptedTurns([LLMUnavailable("Gemini is unavailable (HTTP 503)")])
    result = await NaiveAgent(llm, "m", TOOLS, RecordingInvoker(), system_prompt="s").run("go")
    assert result.stop == "error"
    assert result.error is not None and "503" in result.error


# ---------------------------------------------------------------- the plain (unprotected) invoker


def _registry() -> tuple[Registry, list[str]]:
    registry = Registry()
    threads: list[str] = []

    @registry.tool(kind="source")
    def sync_tool(q: str) -> dict:
        """Sync tool."""
        threads.append(threading.current_thread().name)
        return {"q": q}

    @registry.tool(kind="source")
    async def async_tool(q: str) -> list:
        """Async tool."""
        return [q, q]

    @registry.tool(kind="sink")
    def broken(q: str) -> None:
        """Always fails."""
        raise ValueError("upstream refused sk-abcdefghijklmnopqrstuvwxyz123456")

    return registry, threads


async def test_the_plain_invoker_runs_sync_tools_off_the_event_loop() -> None:
    registry, threads = _registry()
    result = await PlainInvoker(registry)(ToolCall("c1", "sync_tool", {"q": "x"}))
    assert (result.content, result.is_error) == ({"q": "x"}, False)
    assert threads and threads[0] != threading.main_thread().name


async def test_the_plain_invoker_awaits_async_tools() -> None:
    registry, _ = _registry()
    result = await PlainInvoker(registry)(ToolCall("c1", "async_tool", {"q": "x"}))
    assert result.content == ["x", "x"]


async def test_tool_errors_and_bad_arguments_become_scrubbed_error_results() -> None:
    registry, _ = _registry()
    invoker = PlainInvoker(registry)
    failed = await invoker(ToolCall("c1", "broken", {"q": "x"}))
    assert failed.is_error and "upstream refused" in failed.content
    assert "sk-abc" not in failed.content
    bad = await invoker(ToolCall("c2", "sync_tool", {"nope": 1}))
    assert bad.is_error


async def test_tool_defs_come_from_the_registry_catalog() -> None:
    registry, _ = _registry()
    defs = tool_defs(registry)
    assert [d.name for d in defs] == ["async_tool", "broken", "sync_tool"]
    assert defs[2].parameters["properties"]["q"]["type"] == "string"


# ---------------------------------------------------------------- unprotected baseline, end to end


async def test_the_unprotected_baseline_does_whatever_the_model_asks() -> None:
    from tests.engine._world import World

    world = World()
    model = ScriptedTurns(
        [
            Message("assistant", tool_calls=(ToolCall("c1", "list_rows", {"status": "new"}),)),
            Message(
                "assistant",
                tool_calls=(ToolCall("c2", "pay", {"number": "N-9999", "amount": 4999.0}),),
            ),
            Message("assistant", text="Done."),
        ]
    )
    agent = NaiveAgent(
        model, "m", tool_defs(world.registry), PlainInvoker(world.registry), system_prompt="s"
    )
    result = await agent.run("Process today's new records.")
    assert world.paid == [
        {"number": "N-9999", "amount": 4999.0}
    ]  # no protection: the damage happens
    assert result.stop == "answered" and result.turns == 3
    listed = model.histories[1][-1].tool_results[0].content
    assert (
        isinstance(listed, list) and listed[0]["id"] == "R-101"
    )  # results are plain JSON for the model
