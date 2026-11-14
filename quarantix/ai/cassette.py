"""Cassettes (F07): record model replies once, replay them for free and offline.

Modes: `live` calls the model and records nothing; `record` replays a recording
when one exists, otherwise calls the model and saves the reply; `replay` uses
recordings only (a miss raises CassetteMiss; CI runs this way). The key is a hash
of the canonical request, so key order never matters and identical requests (such
as every arena attempt's first turn) are recorded exactly once.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, TypeVar

from quarantix.ai.llm import (
    CassetteMiss,
    JsonReply,
    LLMClient,
    LLMError,
    Message,
    ToolDef,
    TurnReply,
)

Mode = Literal["live", "record", "replay"]
MODES = ("live", "record", "replay")
Reply = TypeVar("Reply", JsonReply, TurnReply)


def cassette_key(op: str, model: str, request: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"op": op, "model": model, "request": request},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class CassetteLLM:
    def __init__(self, inner: LLMClient | None, directory: Path, mode: Mode) -> None:
        if mode not in MODES:
            raise ValueError(f"invalid cassette mode {mode!r}; use {MODES}")
        if inner is None and mode != "replay":
            raise ValueError(f"mode {mode!r} needs a real model client")
        self.inner = inner
        self.directory = Path(directory)
        self.mode = mode

    def path_for(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    async def json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        max_tokens: int = 4096,
    ) -> JsonReply:
        request = {"system": system, "user": user, "schema": schema, "max_tokens": max_tokens}

        async def call() -> JsonReply:
            assert self.inner is not None
            return await self.inner.json(
                model=model, system=system, user=user, schema=schema, max_tokens=max_tokens
            )

        return await self._run("json", model, request, call, JsonReply.from_wire)

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        request = {
            "system": system,
            "messages": [message.to_wire() for message in messages],
            "tools": [tool.to_wire() for tool in tools],
            "max_tokens": max_tokens,
        }

        async def call() -> TurnReply:
            assert self.inner is not None
            return await self.inner.tool_turn(
                model=model, system=system, messages=messages, tools=tools, max_tokens=max_tokens
            )

        return await self._run("tool_turn", model, request, call, TurnReply.from_wire)

    async def _run(
        self,
        op: str,
        model: str,
        request: Mapping[str, Any],
        call: Callable[[], Awaitable[Reply]],
        decode: Callable[[Mapping[str, Any]], Reply],
    ) -> Reply:
        if self.mode == "live":
            return await call()
        key = cassette_key(op, model, request)
        recorded = await asyncio.to_thread(self._load, key, decode)  # never block the event loop
        if recorded is not None:
            return recorded
        if self.mode == "replay":
            raise CassetteMiss(f"no recording for {op} on {model} (key {key[:12]})")
        reply = await call()
        record = {"op": op, "model": model, "request": request, "reply": reply.to_wire()}
        await asyncio.to_thread(self._save, key, record)
        return reply

    def _load(self, key: str, decode: Callable[[Mapping[str, Any]], Reply]) -> Reply | None:
        path = self.path_for(key)
        try:
            return decode(json.loads(path.read_text(encoding="utf-8"))["reply"])
        except FileNotFoundError:
            return None
        except (ValueError, KeyError, TypeError):  # a corrupted recording counts as missing
            return None

    def _save(self, key: str, record: Mapping[str, Any]) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, indent=2, sort_keys=True, default=str, ensure_ascii=False)
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(text)
            os.replace(temporary, path)  # atomic: a crash never leaves a half-written cassette
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


__all__ = ["MODES", "CassetteLLM", "LLMError", "Mode", "cassette_key"]
