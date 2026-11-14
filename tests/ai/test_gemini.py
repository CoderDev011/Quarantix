"""F07 Gemini client, against real SDK types (google-genai 3.3.0) with a fake transport."""

import asyncio
import warnings

import pytest

from quarantix.ai.gemini import GeminiClient
from quarantix.ai.llm import (
    LLMInvalid,
    LLMRefused,
    LLMTimeout,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolDef,
    ToolResult,
)
from tests.ai._fakes import FakeGemini, gemini_response

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from google.genai import errors, types

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
TOOLS = [
    ToolDef(
        "lookup", "Look something up.", {"type": "object", "properties": {"q": {"type": "string"}}}
    )
]


def _client(fake: FakeGemini, **kwargs: object) -> GeminiClient:
    return GeminiClient(client=fake, backoff_s=0.0, **kwargs)  # type: ignore[arg-type]


async def test_json_requests_structured_output_and_parses_the_reply() -> None:
    fake = FakeGemini([gemini_response([types.Part(text='{"ok": true}')])])
    reply = await _client(fake).json(model="flash", system="Extract.", user="text", schema=SCHEMA)
    assert reply.value == {"ok": True}
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (
        100,
        25,
    )  # thoughts count as output
    config = fake.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert config.system_instruction == "Extract."


async def test_unparseable_json_is_invalid() -> None:
    fake = FakeGemini([gemini_response([types.Part(text="not json")])])
    with pytest.raises(LLMInvalid):
        await _client(fake).json(model="flash", system="s", user="u", schema=SCHEMA)


@pytest.mark.parametrize(
    "finish", [types.FinishReason.SAFETY, types.FinishReason.PROHIBITED_CONTENT]
)
async def test_safety_blocks_are_refusals(finish: types.FinishReason) -> None:
    fake = FakeGemini([gemini_response([types.Part(text="")], finish=finish)])
    with pytest.raises(LLMRefused):
        await _client(fake).json(model="flash", system="s", user="u", schema=SCHEMA)


async def test_a_blocked_prompt_is_a_refusal() -> None:
    blocked = types.GenerateContentResponse(
        prompt_feedback=types.GenerateContentResponsePromptFeedback(
            block_reason=types.BlockedReason.SAFETY
        )
    )
    with pytest.raises(LLMRefused):
        await _client(FakeGemini([blocked])).json(
            model="flash", system="s", user="u", schema=SCHEMA
        )


async def test_tool_turns_declare_tools_and_disable_automatic_calling() -> None:
    call = types.Part(function_call=types.FunctionCall(name="lookup", args={"q": "x"}, id="c1"))
    fake = FakeGemini([gemini_response([call])])
    reply = await _client(fake).tool_turn(
        model="flash-lite", system="s", messages=[Message("user", text="go")], tools=TOOLS
    )
    assert reply.message.tool_calls == (ToolCall("c1", "lookup", {"q": "x"}),)
    config = fake.calls[0]["config"]
    declaration = config.tools[0].function_declarations[0]
    assert (declaration.name, declaration.parameters_json_schema) == ("lookup", TOOLS[0].parameters)
    assert config.automatic_function_calling.disable is True


async def test_thought_signatures_are_sent_back_unchanged_on_the_next_turn() -> None:
    signed = types.Part(
        function_call=types.FunctionCall(name="lookup", args={"q": "x"}, id="c1"),
        thought_signature=b"sig-123",
    )
    fake = FakeGemini([gemini_response([signed]), gemini_response([types.Part(text="all done")])])
    client = _client(fake)
    first = await client.tool_turn(
        model="flash-lite", system="s", messages=[Message("user", text="go")], tools=TOOLS
    )
    history = [
        Message("user", text="go"),
        first.message,
        Message("tool", tool_results=(ToolResult("c1", "lookup", {"answer": 42}),)),
    ]
    second = await client.tool_turn(model="flash-lite", system="s", messages=history, tools=TOOLS)
    assert second.message.text == "all done"
    sent = fake.calls[1]["contents"]
    assert sent[1].parts[0].thought_signature == b"sig-123"
    response_part = sent[2].parts[0].function_response
    assert (response_part.id, response_part.name, response_part.response) == (
        "c1",
        "lookup",
        {"result": {"answer": 42}},
    )


async def test_tool_calls_without_ids_get_local_ids() -> None:
    call = types.Part(function_call=types.FunctionCall(name="lookup", args={}))
    reply = await _client(FakeGemini([gemini_response([call])])).tool_turn(
        model="m", system="s", messages=[Message("user", text="go")], tools=TOOLS
    )
    assert reply.message.tool_calls[0].id  # non-empty


async def test_rate_limits_are_retried_then_succeed() -> None:
    fake = FakeGemini(
        [
            errors.APIError(429, {"error": {"message": "slow down"}}),
            gemini_response([types.Part(text='{"ok": true}')]),
        ]
    )
    reply = await _client(fake).json(model="flash", system="s", user="u", schema=SCHEMA)
    assert reply.value == {"ok": True}
    assert len(fake.calls) == 2


async def test_persistent_server_errors_become_unavailable() -> None:
    fake = FakeGemini([errors.APIError(503, {"error": {"message": "down"}})] * 3)
    with pytest.raises(LLMUnavailable):
        await _client(fake).json(model="flash", system="s", user="u", schema=SCHEMA)
    assert len(fake.calls) == 3  # one try + two retries


async def test_client_errors_are_not_retried() -> None:
    fake = FakeGemini([errors.APIError(400, {"error": {"message": "bad request"}})])
    with pytest.raises(LLMInvalid):
        await _client(fake).json(model="flash", system="s", user="u", schema=SCHEMA)
    assert len(fake.calls) == 1


async def test_slow_calls_time_out() -> None:
    class Slow(FakeGemini):
        async def generate_content(self, **kwargs: object) -> object:
            self.calls.append(dict(kwargs))
            await asyncio.sleep(5)

    fake = Slow([])
    with pytest.raises(LLMTimeout):
        await _client(fake, timeout_s=0.01).json(model="flash", system="s", user="u", schema=SCHEMA)
    assert len(fake.calls) == 3


def test_the_api_key_never_appears_in_the_client_repr() -> None:
    client = GeminiClient(api_key="AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKE12")
    assert "AIza" not in repr(client)
