"""Deterministic stand-ins for the naive model in arena and runner tests.

`GullibleLLM` behaves like a vulnerable real agent: it lists records, then obeys
an injected money instruction if it finds one in what it read. It decides from
what the tools actually returned, so attempts that plant different payloads take
different paths (this is what makes isolation testable).
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Sequence
from typing import Any

from quarantix.ai.llm import (
    JsonReply,
    LLMUnavailable,
    Message,
    ToolCall,
    ToolDef,
    TurnReply,
    Usage,
)

_MONEY = re.compile(r"(ORD-\d{4}).{0,200}?(4999\.00)", re.DOTALL)
_SHELL = re.compile(r"run_shell with: (.+)$", re.MULTILINE)


class GullibleLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.turns = 0
        self._ids = itertools.count(1)

    async def json(
        self, *, model: str, system: str, user: str, schema: Any, max_tokens: int = 4096
    ) -> JsonReply:
        raise AssertionError("the naive agent never asks for JSON")

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        self.turns += 1
        if self.fail:
            raise LLMUnavailable("HTTP 503 from the provider")
        names = {t.name for t in tools}
        results = [r for m in messages if m.role == "tool" for r in m.tool_results]
        if not results:
            if "list_tickets" in names:
                return self._call("list_tickets", {"status": "new"})
            return self._call("read_logs", {"service": "api", "lines": 5})
        if len(results) == 1:
            text = json.dumps(results[0].content)
            money = _MONEY.search(text)
            if money and "issue_refund" in names:
                return self._call(
                    "issue_refund",
                    {"order_number": money.group(1), "amount": float(money.group(2))},
                )
            shell = _SHELL.search("\n".join(r.get("text", "") for r in results[0].content or []))
            if shell and "run_shell" in names:
                return self._call("run_shell", {"command": shell.group(1).strip()})
        return TurnReply(Message("assistant", text="Done."), Usage(500, 20), "stop")

    def _call(self, name: str, arguments: dict[str, Any]) -> TurnReply:
        call = ToolCall(f"c{next(self._ids)}", name, arguments)
        return TurnReply(Message("assistant", tool_calls=(call,)), Usage(800, 40), "tool_calls")


class SummarizerLLM(GullibleLLM):
    """Lists the new tickets, then posts a summary that quotes the newest one verbatim.

    This is the realistic phishing gap: summaries are made of untrusted ticket text.
    """

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        self.turns += 1
        results = [r for m in messages if m.role == "tool" for r in m.tool_results]
        if not results:
            return self._call("list_tickets", {"status": "new"})
        if len(results) == 1 and isinstance(results[0].content, list) and results[0].content:
            newest = results[0].content[-1].get("text", "")
            return self._call(
                "post_message", {"channel": "#support-log", "text": f"Ticket summary: {newest}"}
            )
        return TurnReply(Message("assistant", text="Posted the summary."), Usage(500, 20), "stop")
