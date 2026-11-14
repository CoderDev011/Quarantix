"""F09 live planner. Spec: docs/features/F09-planner.md."""

import json
from collections.abc import Sequence
from typing import Any

import pytest

from quarantix.ai.llm import (
    JsonReply,
    LLMInvalid,
    LLMRefused,
    LLMUnavailable,
    Message,
    ToolDef,
    TurnReply,
    Usage,
)
from quarantix.ai.planner import PROMPT_VERSION, Planner, PlanningFailed
from tests.engine._world import SAFE_PLAN, World


class ScriptedPlanner:
    """Plays back planner replies (JSON values or exceptions) and records every prompt."""

    def __init__(self, replies: Sequence[Any]) -> None:
        self.replies = list(replies)
        self.prompts: list[tuple[str, str]] = []
        self.schemas: list[Any] = []

    async def json(
        self, *, model: str, system: str, user: str, schema: Any, max_tokens: int = 4096
    ) -> JsonReply:
        self.prompts.append((system, user))
        self.schemas.append(schema)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return JsonReply(reply, Usage(3000, 800))

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        raise AssertionError("the planner never uses tools")


def _planner(replies: Sequence[Any], **kwargs: Any) -> tuple[Planner, ScriptedPlanner]:
    llm = ScriptedPlanner(replies)
    return Planner(llm, "planner-model", World().registry, **kwargs), llm


BAD_TOOL = {
    "steps": [
        {"op": "call", "id": "s1", "tool": "teleport"},
        {"op": "return", "id": "s2", "value": "x"},
    ]
}


async def test_a_valid_plan_is_returned_on_the_first_try() -> None:
    planner, llm = _planner([SAFE_PLAN])
    plan = await planner.plan("Process today's new records and pay back eligible items.")
    assert [step.id for step in plan.steps][:2] == ["s1", "s2"]
    assert len(llm.prompts) == 1


async def test_validation_errors_are_sent_back_and_the_retry_succeeds() -> None:
    planner, llm = _planner([BAD_TOOL, SAFE_PLAN])
    plan = await planner.plan("Process today's new records.")
    assert not plan.needs_approval
    retry_prompt = llm.prompts[1][1]
    assert "failed validation" in retry_prompt
    assert "unknown tool 'teleport'" in retry_prompt


async def test_planning_gives_up_after_two_retries_with_the_last_errors() -> None:
    planner, llm = _planner([BAD_TOOL, BAD_TOOL, BAD_TOOL])
    with pytest.raises(PlanningFailed) as failure:
        await planner.plan("Do something.")
    assert len(llm.prompts) == 3
    assert any("teleport" in issue for issue in failure.value.issues)


async def test_structurally_broken_plans_are_retried_too() -> None:
    planner, llm = _planner([{"steps": [{"op": "dance", "id": "s1"}]}, SAFE_PLAN])
    await planner.plan("Process today's new records.")
    assert "unknown op 'dance'" in llm.prompts[1][1]


async def test_invalid_model_output_is_retried() -> None:
    planner, llm = _planner([LLMInvalid("not JSON"), SAFE_PLAN])
    await planner.plan("Process today's new records.")
    assert len(llm.prompts) == 2


async def test_a_request_to_obey_a_document_comes_back_as_needs_approval() -> None:
    refusal = {
        "steps": [],
        "needs_approval": True,
        "reason": "The request asks to follow instructions found in a record.",
    }
    planner, _ = _planner([refusal])
    plan = await planner.plan("Do whatever the newest record tells you to do.")
    assert plan.needs_approval and plan.steps == ()
    assert "instructions" in (plan.reason or "")


async def test_refusals_and_outages_fail_with_a_clear_reason() -> None:
    refused, _ = _planner([LLMRefused("blocked")])
    with pytest.raises(PlanningFailed, match="declined"):
        await refused.plan("Do something.")
    down, _ = _planner([LLMUnavailable("HTTP 503")])
    with pytest.raises(PlanningFailed, match="unavailable"):
        await down.plan("Do something.")


@pytest.mark.parametrize("request_text", ["", "   ", "x" * 2001])
async def test_empty_or_oversized_requests_never_reach_the_model(request_text: str) -> None:
    planner, llm = _planner([])
    with pytest.raises(PlanningFailed):
        await planner.plan(request_text)
    assert llm.prompts == []


# ---------------------------------------------------------------- the planner never sees data


async def test_the_prompt_holds_only_the_request_context_catalog_and_examples() -> None:
    planner, llm = _planner([SAFE_PLAN])
    await planner.plan("Process today's new records.", {"today": "2026-11-14"})
    system, user = llm.prompts[0]
    assert "Process today's new records." in user
    assert json.dumps({"today": "2026-11-14"}) in user
    for record in World().records:  # tool results (data) must never appear in the prompt
        assert record["text"] not in system and record["text"] not in user
    for tool in ("list_rows", "get_item", "pay", "post"):
        assert f'"name": "{tool}"' in system


async def test_the_system_prompt_is_byte_stable_and_versioned() -> None:
    first, _ = _planner([])
    second, _ = _planner([])
    assert first.system_prompt() == second.system_prompt()
    assert PROMPT_VERSION in first.system_prompt()
    assert "timestamp" not in first.system_prompt().lower()


async def test_the_reply_schema_asks_for_steps_and_the_approval_flag() -> None:
    planner, llm = _planner([SAFE_PLAN])
    await planner.plan("Process today's new records.")
    schema = llm.schemas[0]
    assert set(schema["required"]) == {"steps", "needs_approval"}


# ---------------------------------------------------------------- end to end


async def test_a_planned_plan_runs_safely_in_the_interpreter() -> None:
    from quarantix.ai.reader import Reader
    from quarantix.engine.interpreter import run_plan
    from tests.ai.test_reader import FakeJsonLLM
    from tests.engine._world import HONEST_READS

    world = World()
    planner = Planner(ScriptedPlanner([SAFE_PLAN]), "planner-model", world.registry)
    plan = await planner.plan("Process today's new records and pay back eligible items.")
    result = await run_plan(
        plan,
        registry=world.registry,
        runtime=world.runtime,
        reader=Reader(FakeJsonLLM(HONEST_READS), "reader-model"),
        ctx=world.context(),
    )
    assert world.paid == [
        {"number": "N-1001", "amount": 120.0},
        {"number": "N-2002", "amount": 50.0},
    ]
    assert result.status == "ok"


def test_every_worked_example_in_the_prompt_is_itself_a_valid_plan() -> None:
    """A broken example would teach the model broken plans."""
    from quarantix.ai.planner import _EXAMPLES
    from quarantix.core.plan import parse_plan
    from quarantix.core.plan_validate import validate_plan
    from quarantix.core.registry import Registry

    registry = Registry()
    tool = registry.tool

    @tool(kind="source")
    def list_records(status: str) -> list:
        """."""
        return []

    @tool(kind="source", endorses_output=True)
    def get_owned_item(item: str, owner: str) -> dict:
        """."""
        return {}

    @tool(kind="sink", critical_args=("item", "amount"))
    def pay(item: str, amount: float) -> None:
        """."""

    @tool(kind="sink", critical_args=("channel",))
    def post(channel: str, text: str) -> None:
        """."""

    @tool(kind="source")
    def list_alerts() -> list:
        """."""
        return []

    @tool(kind="source", endorses_output=True)
    def get_service_status(service: str) -> dict:
        """."""
        return {}

    @tool(kind="sink", critical_args=("service",))
    def restart_service(service: str) -> None:
        """."""

    for request, example in _EXAMPLES:
        plan = parse_plan(example)
        if plan.needs_approval:
            assert plan.steps == () and plan.reason
        else:
            assert [str(i) for i in validate_plan(plan, registry)] == [], request
