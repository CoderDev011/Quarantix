"""Spend meter (F07): a hard budget for paid model calls.

Cost = input tokens x input price + output tokens x output price (per 1M tokens).
At `economy_at` the economy signal turns on (the arena switches to local models);
at `hard_cap` paid calls are refused with BudgetExhausted. Local (free) models are
counted but never refused. The meter's number is an estimate: the provider's
console balance is the truth (record it in docs/SPIKES.md before paid runs).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from quarantix.ai.llm import (
    BudgetExhausted,
    JsonReply,
    LLMClient,
    Message,
    ToolDef,
    TurnReply,
    Usage,
)

Listener = Callable[[str, Usage, float], None]


class SpendMeter:
    def __init__(
        self,
        prices: Mapping[str, tuple[float, float]],
        *,
        economy_at: float = 8.0,
        hard_cap: float = 10.0,
        on_record: Listener | None = None,
        starting_total: float = 0.0,
    ) -> None:
        self.prices = dict(prices)
        self.economy_at = economy_at
        self.hard_cap = hard_cap
        self.on_record = on_record
        self.total = starting_total
        self.calls: Counter[str] = Counter()

    @property
    def economy(self) -> bool:
        return self.total >= self.economy_at

    def price(self, model: str) -> tuple[float, float]:
        try:
            return self.prices[model]
        except KeyError:
            raise ValueError(f"no price configured for paid model {model!r}") from None

    def check(self, model: str, *, paid: bool = True) -> None:
        """Raise before a call that must not happen."""
        if not paid:
            return
        self.price(model)
        if self.total >= self.hard_cap:
            raise BudgetExhausted(
                f"spend cap ${self.hard_cap:.2f} reached (${self.total:.4f} spent)"
            )

    def record(self, model: str, usage: Usage, *, paid: bool = True) -> float:
        self.calls[model] += 1
        cost = 0.0
        if paid:
            input_price, output_price = self.price(model)
            cost = (
                usage.input_tokens * input_price + usage.output_tokens * output_price
            ) / 1_000_000
            self.total += cost
        if self.on_record is not None:
            self.on_record(model, usage, cost)
        return cost


class MeteredLLM:
    """Checks the cap before each call and records its usage after."""

    def __init__(self, inner: LLMClient, meter: SpendMeter, *, paid: bool = True) -> None:
        self.inner = inner
        self.meter = meter
        self.paid = paid

    async def json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: Mapping[str, Any],
        max_tokens: int = 4096,
    ) -> JsonReply:
        self.meter.check(model, paid=self.paid)
        reply = await self.inner.json(
            model=model, system=system, user=user, schema=schema, max_tokens=max_tokens
        )
        self.meter.record(model, reply.usage, paid=self.paid)
        return reply

    async def tool_turn(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolDef],
        max_tokens: int = 4096,
    ) -> TurnReply:
        self.meter.check(model, paid=self.paid)
        reply = await self.inner.tool_turn(
            model=model, system=system, messages=messages, tools=tools, max_tokens=max_tokens
        )
        self.meter.record(model, reply.usage, paid=self.paid)
        return reply
