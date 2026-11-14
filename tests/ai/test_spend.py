"""F07 spend meter: costs, the economy signal and the hard cap."""

import pytest

from quarantix.ai.llm import BudgetExhausted, Usage
from quarantix.ai.spend import MeteredLLM, SpendMeter
from tests.ai._fakes import ScriptedLLM

PRICES = {"flash-lite": (0.25, 1.50), "flash": (0.75, 3.75)}


def test_cost_is_tokens_times_price_per_million() -> None:
    meter = SpendMeter(PRICES)
    cost = meter.record("flash", Usage(input_tokens=6000, output_tokens=3000))
    assert cost == pytest.approx(6000 * 0.75 / 1e6 + 3000 * 3.75 / 1e6)
    assert meter.total == pytest.approx(cost)


def test_the_economy_signal_switches_on_at_the_threshold() -> None:
    meter = SpendMeter(PRICES, economy_at=0.01, hard_cap=1.0)
    assert not meter.economy
    meter.record("flash", Usage(10_000, 0))  # $0.0075: still below the $0.01 threshold
    assert not meter.economy
    meter.record("flash", Usage(10_000, 0))  # $0.0150 in total
    assert meter.economy


def test_paid_calls_are_refused_at_the_hard_cap() -> None:
    meter = SpendMeter(PRICES, hard_cap=0.001)
    meter.record("flash", Usage(10_000, 0))
    with pytest.raises(BudgetExhausted):
        meter.check("flash")


def test_free_models_are_counted_but_never_refused() -> None:
    meter = SpendMeter(PRICES, hard_cap=0.0)
    meter.check("qwen2.5:3b", paid=False)
    assert meter.record("qwen2.5:3b", Usage(5000, 500), paid=False) == 0.0
    assert meter.calls["qwen2.5:3b"] == 1


def test_a_paid_model_without_a_price_is_a_configuration_error() -> None:
    with pytest.raises(ValueError, match="no price"):
        SpendMeter(PRICES).check("mystery-model")


def test_every_recorded_call_reaches_the_listener() -> None:
    seen = []
    meter = SpendMeter(PRICES, on_record=lambda model, usage, cost: seen.append((model, cost)))
    meter.record("flash-lite", Usage(1_000_000, 0))
    assert seen == [("flash-lite", pytest.approx(0.25))]


async def test_the_metered_client_records_usage_and_enforces_the_cap() -> None:
    meter = SpendMeter(PRICES, hard_cap=0.0011)
    llm = MeteredLLM(ScriptedLLM(), meter)
    await llm.json(model="flash", system="s", user="u", schema={})
    assert meter.total == pytest.approx(1000 * 0.75 / 1e6 + 100 * 3.75 / 1e6)
    with pytest.raises(BudgetExhausted):
        await llm.json(model="flash", system="s", user="u", schema={})
