"""Gemini client (F07), written against google-genai 3.3.0 (inspected 2026-11-14).

JSON mode uses `response_mime_type="application/json"` + `response_json_schema`.
Tool turns declare tools with `parameters_json_schema` and disable the SDK's
automatic function calling (we run tools ourselves, through the Gate). Gemini 3
attaches thought signatures to its replies and requires them back unchanged, so
each assistant message keeps the raw reply in `provider_state` and is rebuilt
from it on the next turn.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
import warnings
from collections.abc import Mapping, Sequence
from typing import Any

from quarantix.ai.llm import (
    JsonReply,
    LLMError,
    LLMInvalid,
    LLMRefused,
    LLMTimeout,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolDef,
    TurnReply,
    Usage,
)

with warnings.catch_warnings():  # the SDK emits SyntaxWarnings from its own source on import
    warnings.simplefilter("ignore")
    from google import genai
    from google.genai import errors, types

_REFUSALS = frozenset(
    {
        types.FinishReason.SAFETY,
        types.FinishReason.PROHIBITED_CONTENT,
        types.FinishReason.BLOCKLIST,
        types.FinishReason.SPII,
        types.FinishReason.RECITATION,
        types.FinishReason.MODEL_ARMOR,
    }
)


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any = None,
        timeout_s: float = 30.0,
        retries: int = 2,
        backoff_s: float = 0.5,
        concurrency: int = 8,
    ) -> None:
        self._client = client if client is not None else genai.Client(api_key=api_key)
        self.timeout_s = timeout_s
        self.retries = retries
        self.backoff_s = backoff_s
        self._limit = asyncio.Semaphore(concurrency)

    def __repr__(self) -> str:  # never show the key
        return f"GeminiClient(timeout_s={self.timeout_s}, retries={self.retries})"

    async def json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        max_tokens: int = 4096,
    ) -> JsonReply:
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=dict(schema),
            max_output_tokens=max_tokens,
        )
        response = await self._generate(model, user, config)
        text = "".join(part.text or "" for part in _parts(response) if not part.thought)
        try:
            value = json.loads(text)
        except ValueError:
            raise LLMInvalid("Gemini returned text that is not valid JSON") from None
        return JsonReply(value, _usage(response))

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=dict(tool.parameters),
                        )
                        for tool in tools
                    ]
                )
            ],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=max_tokens,
        )
        response = await self._generate(model, [_content(message) for message in messages], config)
        candidate = response.candidates[0]  # _generate guarantees one exists
        if candidate.finish_reason == types.FinishReason.MALFORMED_FUNCTION_CALL:
            raise LLMInvalid("Gemini produced a malformed function call")
        texts, calls = [], []
        for part in _parts(response):
            if part.function_call is not None:
                call = part.function_call
                calls.append(
                    ToolCall(
                        call.id or f"call-{uuid.uuid4().hex[:8]}",
                        call.name or "",
                        dict(call.args or {}),
                    )
                )
            elif part.text and not part.thought:
                texts.append(part.text)
        state = (
            candidate.content.model_dump(mode="json", exclude_none=True)
            if candidate.content
            else None
        )
        message = Message(
            "assistant", text="".join(texts) or None, tool_calls=tuple(calls), provider_state=state
        )
        stop = candidate.finish_reason.name.lower() if candidate.finish_reason else "stop"
        return TurnReply(message, _usage(response), stop)

    async def _generate(
        self, model: str, contents: Any, config: types.GenerateContentConfig
    ) -> Any:
        last: LLMError | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                await asyncio.sleep(self.backoff_s * 2 ** (attempt - 1) * random.uniform(0.5, 1.5))  # noqa: S311
            try:
                async with self._limit, asyncio.timeout(self.timeout_s):
                    response = await self._client.aio.models.generate_content(
                        model=model, contents=contents, config=config
                    )
            except TimeoutError:
                last = LLMTimeout(f"Gemini did not answer within {self.timeout_s}s")
                continue
            except errors.APIError as exc:
                code = getattr(exc, "code", None) or 0
                if code == 429 or code >= 500:
                    last = LLMUnavailable(f"Gemini is unavailable (HTTP {code})")
                    continue
                raise LLMInvalid(f"Gemini rejected the request (HTTP {code})") from None
            _check_refusal(response)
            return response
        assert last is not None
        raise last


def _check_refusal(response: Any) -> None:
    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise LLMRefused(f"Gemini blocked the prompt ({feedback.block_reason})")
    if not response.candidates:
        raise LLMRefused("Gemini returned no candidates")
    if response.candidates[0].finish_reason in _REFUSALS:
        raise LLMRefused(f"Gemini declined ({response.candidates[0].finish_reason.name})")


def _parts(response: Any) -> list[types.Part]:
    content = response.candidates[0].content
    return list(content.parts or []) if content is not None else []


def _usage(response: Any) -> Usage:
    usage = response.usage_metadata
    if usage is None:
        return Usage()
    output = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    return Usage(usage.prompt_token_count or 0, output)


def _content(message: Message) -> types.Content:
    if message.role == "user":
        return types.Content(role="user", parts=[types.Part(text=message.text or "")])
    if message.role == "assistant":
        if message.provider_state is not None:  # replay Gemini's own reply, signatures included
            return types.Content.model_validate(message.provider_state)
        parts = [types.Part(text=message.text)] if message.text else []
        parts += [
            types.Part(
                function_call=types.FunctionCall(id=c.id, name=c.name, args=dict(c.arguments))
            )
            for c in message.tool_calls
        ]
        return types.Content(role="model", parts=parts)
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=result.call_id,
                    name=result.name,
                    response={"error": result.content}
                    if result.is_error
                    else {"result": result.content},
                )
            )
            for result in message.tool_results
        ],
    )
