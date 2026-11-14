"""Test doubles for the LLM layer. The Gemini fake returns real SDK response types."""

from __future__ import annotations

import warnings
from collections.abc import Callable, Sequence
from typing import Any

from quarantix.ai.llm import JsonReply, Message, ToolDef, TurnReply, Usage

with warnings.catch_warnings():  # the SDK's own module emits SyntaxWarnings on import
    warnings.simplefilter("ignore")
    from google.genai import types


def gemini_response(
    parts: Sequence[types.Part],
    *,
    finish: types.FinishReason = types.FinishReason.STOP,
    prompt_tokens: int = 100,
    output_tokens: int = 20,
    thought_tokens: int = 5,
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=list(parts)), finish_reason=finish
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
            thoughts_token_count=thought_tokens,
        ),
    )


class FakeGemini:
    """Mimics `genai.Client().aio.models.generate_content`, replaying scripted replies."""

    def __init__(self, replies: Sequence[types.GenerateContentResponse | BaseException]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []
        self.aio = self
        self.models = self

    async def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config})
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply


class ScriptedLLM:
    """A provider-neutral fake LLMClient for cassette and meter tests."""

    def __init__(self, json_value: Any = None, turn: Message | None = None) -> None:
        self.json_value = json_value if json_value is not None else {"ok": True}
        self.turn = turn or Message(role="assistant", text="done")
        self.json_calls = 0
        self.turn_calls = 0
        self.on_call: Callable[[], None] | None = None

    async def json(
        self, *, model: str, system: str, user: str, schema: Any, max_tokens: int = 4096
    ) -> JsonReply:
        self.json_calls += 1
        if self.on_call:
            self.on_call()
        return JsonReply(self.json_value, Usage(1000, 100))

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        self.turn_calls += 1
        return TurnReply(self.turn, Usage(2000, 200), "stop")
