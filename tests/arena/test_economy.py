"""F15 budget behavior: at $8 total spend the arena switches to local models."""

from quarantix.ai.llm import Usage
from quarantix.ai.spend import SpendMeter
from quarantix.api.runtime import build_models, parse_prices
from quarantix.arena.defenders import Brains, BrainsSwitch
from tests.arena._agents import GullibleLLM
from tests.packs._reader import HonestReader


def test_economy_switch_at_8_dollars() -> None:
    meter = SpendMeter({"paid": (1_000_000.0, 0.0)}, economy_at=8.0, hard_cap=10.0)
    normal = Brains(GullibleLLM(), "paid", HonestReader(), "paid")
    economy = Brains(GullibleLLM(), "local", HonestReader(), "economy: local")
    switch = BrainsSwitch(normal, economy, lambda: meter.economy)
    assert switch().label == "paid"
    meter.record("paid", Usage(7, 0))  # $7
    assert switch().label == "paid"
    meter.record("paid", Usage(1, 0))  # $8
    assert switch().label == "economy: local"


def test_prices_parse_and_reject_garbage() -> None:
    assert parse_prices("a:0.1/0.4, b-c:1/2") == {"a": (0.1, 0.4), "b-c": (1.0, 2.0)}
    try:
        parse_prices("a:x/y")
    except ValueError as exc:
        assert "model:in/out" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("garbage prices must be rejected")


def test_without_a_paid_key_the_local_model_is_said_honestly() -> None:
    models = build_models({"LLM_MODE": "live", "GEMINI_API_KEY": "replace-me", "OLLAMA_MODEL": "m"})
    assert models.brains().label == "local: m"
    assert models.planner is None
