"""Ollama client (F07): the free local model (Red Agent, offline fallback, weak baseline).

Uses Ollama's `/api/chat` with `stream: false`: JSON mode passes the schema as
`format`; tool turns pass `tools` and read `message.tool_calls`. `keep_alive`
keeps the model loaded between arena attempts (a cold load costs seconds on CPU).
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from quarantix.ai.llm import (
    JsonReply,
    LLMError,
    LLMInvalid,
    LLMTimeout,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolDef,
    TurnReply,
    Usage,
)


class OllamaClient:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        *,
        timeout_s: float = 120.0,
        retries: int = 2,
        backoff_s: float = 0.5,
        concurrency: int = 1,
        keep_alive: str = "30m",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.retries = retries
        self.backoff_s = backoff_s
        self.keep_alive = keep_alive
        self._limit = asyncio.Semaphore(concurrency)
        self._http: httpx.AsyncClient | None = None

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        max_tokens: int = 4096,
    ) -> JsonReply:
        data = await self._chat(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "format": dict(schema),
                "options": {"num_predict": max_tokens},
            }
        )
        try:
            value = json.loads(data.get("message", {}).get("content", ""))
        except ValueError:
            raise LLMInvalid("Ollama returned text that is not valid JSON") from None
        return JsonReply(value, _usage(data))

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        data = await self._chat(
            {
                "model": model,
                "messages": [{"role": "system", "content": system}, *_messages(messages)],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": dict(tool.parameters),
                        },
                    }
                    for tool in tools
                ],
                "options": {"num_predict": max_tokens},
            }
        )
        reply = data.get("message", {})
        calls = []
        for index, raw in enumerate(reply.get("tool_calls") or ()):
            function = raw.get("function", {})
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    raise LLMInvalid("Ollama produced tool arguments that are not JSON") from None
            calls.append(
                ToolCall(
                    raw.get("id") or f"call-{index}-{uuid.uuid4().hex[:6]}",
                    function.get("name", ""),
                    arguments,
                )
            )
        message = Message("assistant", text=reply.get("content") or None, tool_calls=tuple(calls))
        return TurnReply(message, _usage(data), data.get("done_reason") or "stop")

    async def _chat(self, body: dict[str, Any]) -> dict[str, Any]:
        body = {**body, "stream": False, "keep_alive": self.keep_alive}
        if self._http is None:
            self._http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_s)
        last: LLMError | None = None
        for attempt in range(self.retries + 1):
            if attempt:
                await asyncio.sleep(self.backoff_s * 2 ** (attempt - 1) * random.uniform(0.5, 1.5))  # noqa: S311
            try:
                async with self._limit:
                    response = await self._http.post("/api/chat", json=body)
            except httpx.TimeoutException:
                last = LLMTimeout(f"Ollama did not answer within {self.timeout_s}s")
                continue
            except httpx.TransportError:
                last = LLMUnavailable(f"Ollama is not reachable at {self.base_url}")
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last = LLMUnavailable(f"Ollama is unavailable (HTTP {response.status_code})")
                continue
            if response.status_code >= 400:
                raise LLMInvalid(f"Ollama rejected the request (HTTP {response.status_code})")
            try:
                return response.json()
            except ValueError:
                raise LLMInvalid("Ollama returned a non-JSON response") from None
        assert last is not None
        raise last


def _messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            out += [
                {"role": "tool", "content": json.dumps(r.content, default=str), "tool_name": r.name}
                for r in message.tool_results
            ]
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.text or ""}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": dict(c.arguments)}}
                    for c in message.tool_calls
                ]
            out.append(entry)
        else:
            out.append({"role": "user", "content": message.text or ""})
    return out


def _usage(data: Mapping[str, Any]) -> Usage:
    return Usage(int(data.get("prompt_eval_count") or 0), int(data.get("eval_count") or 0))
