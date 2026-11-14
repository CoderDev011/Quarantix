"""LLM layer interface (F07): two operations, provider-neutral messages, typed errors.

`json`: system + user text + JSON schema -> a parsed JSON value (callers validate it).
`tool_turn`: system + history + tool definitions -> the model's next message.
Every client (Gemini, Ollama, the cassette wrapper, the spend meter) implements this.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["user", "assistant", "tool"]


class LLMError(Exception):
    """Base class. Messages never contain API keys or prompt text."""


class LLMRefused(LLMError):
    """The provider declined (safety block, blocked prompt). Callers treat it as a safe failure."""


class LLMInvalid(LLMError):
    """The reply was unusable (bad JSON, malformed tool call) or the request was rejected (4xx)."""


class LLMTimeout(LLMError):
    """No reply within the time limit, after retries."""


class LLMUnavailable(LLMError):
    """Rate limited or provider down (429 / 5xx), after retries."""


class BudgetExhausted(LLMError):
    """The spend meter's hard cap was reached; paid calls are refused (switch to replay)."""


class CassetteMiss(LLMError):
    """Replay mode found no recording for this request."""


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0  # includes any thinking tokens the provider bills as output


@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str
    description: str
    parameters: Mapping[str, Any]

    def to_wire(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": dict(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    content: Any
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    # The provider's raw reply (JSON-safe). Some providers require it back unchanged on the
    # next turn (Gemini thought signatures); clients rebuild the request from it.
    provider_state: Any = field(default=None, compare=False)

    def to_wire(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "text": self.text,
            "tool_calls": [
                {"id": c.id, "name": c.name, "arguments": dict(c.arguments)}
                for c in self.tool_calls
            ],
            "tool_results": [
                {"call_id": r.call_id, "name": r.name, "content": r.content, "is_error": r.is_error}
                for r in self.tool_results
            ],
            "provider_state": self.provider_state,
        }

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any]) -> Message:
        return cls(
            role=wire["role"],
            text=wire.get("text"),
            tool_calls=tuple(
                ToolCall(c["id"], c["name"], c["arguments"]) for c in wire.get("tool_calls", ())
            ),
            tool_results=tuple(
                ToolResult(r["call_id"], r["name"], r["content"], r.get("is_error", False))
                for r in wire.get("tool_results", ())
            ),
            provider_state=wire.get("provider_state"),
        )


@dataclass(frozen=True, slots=True)
class JsonReply:
    value: Any
    usage: Usage

    def to_wire(self) -> dict[str, Any]:
        return {"value": self.value, "usage": _usage_wire(self.usage)}

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any]) -> JsonReply:
        return cls(wire["value"], Usage(**wire["usage"]))


@dataclass(frozen=True, slots=True)
class TurnReply:
    message: Message
    usage: Usage
    stop: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "message": self.message.to_wire(),
            "usage": _usage_wire(self.usage),
            "stop": self.stop,
        }

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any]) -> TurnReply:
        return cls(Message.from_wire(wire["message"]), Usage(**wire["usage"]), wire["stop"])


def _usage_wire(usage: Usage) -> dict[str, int]:
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}


class LLMClient(Protocol):
    async def json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        max_tokens: int = 4096,
    ) -> JsonReply: ...

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply: ...
