"""F07 Ollama client, with Ollama's HTTP API mocked by respx."""

import json

import httpx
import pytest
import respx

from quarantix.ai.llm import LLMInvalid, LLMUnavailable, Message, ToolDef, ToolResult
from quarantix.ai.ollama import OllamaClient

BASE = "http://ollama.test:11434"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
TOOLS = [
    ToolDef(
        "lookup", "Look something up.", {"type": "object", "properties": {"q": {"type": "string"}}}
    )
]


def _reply(message: dict, prompt: int = 50, out: int = 10) -> httpx.Response:
    return httpx.Response(
        200, json={"message": message, "prompt_eval_count": prompt, "eval_count": out}
    )


@respx.mock
async def test_json_sends_the_schema_as_the_format_and_keeps_the_model_loaded() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=_reply({"role": "assistant", "content": '{"ok": true}'})
    )
    reply = await OllamaClient(BASE).json(
        model="qwen2.5:3b", system="Extract.", user="text", schema=SCHEMA
    )
    assert reply.value == {"ok": True}
    assert (reply.usage.input_tokens, reply.usage.output_tokens) == (50, 10)
    body = json.loads(route.calls[0].request.content)
    assert body["format"] == SCHEMA
    assert body["stream"] is False
    assert body["keep_alive"]
    assert body["messages"][0] == {"role": "system", "content": "Extract."}


@respx.mock
async def test_tool_turns_send_tools_and_parse_tool_calls() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=_reply(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "lookup", "arguments": {"q": "x"}}}],
            }
        )
    )
    reply = await OllamaClient(BASE).tool_turn(
        model="qwen2.5:3b", system="s", messages=[Message("user", text="go")], tools=TOOLS
    )
    (call,) = reply.message.tool_calls
    assert (call.name, call.arguments) == ("lookup", {"q": "x"})
    assert call.id
    body = json.loads(route.calls[0].request.content)
    assert body["tools"][0]["function"]["name"] == "lookup"


@respx.mock
async def test_tool_results_are_sent_as_tool_messages() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        return_value=_reply({"role": "assistant", "content": "done"})
    )
    history = [
        Message("user", text="go"),
        Message("tool", tool_results=(ToolResult("c1", "lookup", {"answer": 42}),)),
    ]
    await OllamaClient(BASE).tool_turn(
        model="qwen2.5:3b", system="s", messages=history, tools=TOOLS
    )
    sent = json.loads(route.calls[0].request.content)["messages"]
    assert sent[-1]["role"] == "tool"
    assert json.loads(sent[-1]["content"]) == {"answer": 42}


@respx.mock
async def test_server_errors_are_retried_then_unavailable() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(return_value=httpx.Response(500))
    with pytest.raises(LLMUnavailable):
        await OllamaClient(BASE, backoff_s=0.0).json(model="m", system="s", user="u", schema=SCHEMA)
    assert route.call_count == 3


@respx.mock
async def test_unparseable_json_is_invalid() -> None:
    respx.post(f"{BASE}/api/chat").mock(
        return_value=_reply({"role": "assistant", "content": "nope"})
    )
    with pytest.raises(LLMInvalid):
        await OllamaClient(BASE).json(model="m", system="s", user="u", schema=SCHEMA)
