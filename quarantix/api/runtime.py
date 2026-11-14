"""Assembles the product from the environment: domains, models, spend meter, attacker link.

Names match .env.example. Nothing here decides anything; it only wires the parts.
Prices are estimates (USD per 1M input/output tokens) and deliberately conservative;
the provider's console balance is the truth (docs/SPIKES.md ledger).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from quarantix.ai.cassette import CassetteLLM
from quarantix.ai.llm import LLMClient
from quarantix.ai.ollama import OllamaClient
from quarantix.ai.reader import Reader
from quarantix.ai.spend import MeteredLLM, SpendMeter
from quarantix.arena.defenders import Brains, BrainsSwitch
from quarantix.packs.attacker import AttackerLink
from quarantix.packs.loader import load_all
from quarantix.packs.model import Domain

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICES = (
    "gemini-3.1-flash-lite:0.25/1.50,gemini-3.5-flash-lite:0.25/1.50,gemini-3.8-flash:0.60/4.00"
)
_PLACEHOLDERS = frozenset({"", "replace-me"})


def parse_prices(text: str) -> dict[str, tuple[float, float]]:
    """`model:in/out,model2:in/out` -> {model: (in, out)} in USD per 1M tokens."""
    prices: dict[str, tuple[float, float]] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        model, _, pair = item.rpartition(":")
        price_in, _, price_out = pair.partition("/")
        try:
            prices[model] = (float(price_in), float(price_out))
        except ValueError:
            raise ValueError(f"invalid price entry {item!r}: use model:in/out") from None
    return prices


@dataclass(slots=True)
class Models:
    meter: SpendMeter
    brains: BrainsSwitch
    planner: tuple[LLMClient, str] | None
    drafter: tuple[LLMClient, str] | None
    local: tuple[LLMClient, str]
    mode: str
    closers: list[Any]

    async def close(self) -> None:
        for closer in self.closers:
            close = getattr(closer, "aclose", None) or getattr(closer, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result


def build_models(env: Mapping[str, str] | None = None) -> Models:
    env = os.environ if env is None else env
    meter = SpendMeter(
        parse_prices(env.get("MODEL_PRICES", DEFAULT_PRICES)),
        economy_at=float(env.get("SPEND_ECONOMY_AT", "8")),
        hard_cap=float(env.get("SPEND_HARD_CAP", "10")),
    )
    mode = env.get("LLM_MODE", "live")
    cassettes = Path(env.get("AGENTWALL_CASSETTES", str(REPO_ROOT / "cassettes")))
    ollama_model = env.get("OLLAMA_MODEL", "qwen2.5:3b")
    ollama = OllamaClient(env.get("OLLAMA_URL", "http://localhost:11434"))
    closers: list[Any] = [ollama]

    def wrap(inner: LLMClient | None, *, paid: bool) -> LLMClient:
        metered = MeteredLLM(inner, meter, paid=paid) if inner is not None else None
        if mode in ("record", "replay"):
            return CassetteLLM(metered, cassettes, mode)  # type: ignore[arg-type]
        if metered is None:
            raise ValueError("no model client available")
        return metered

    local = wrap(ollama, paid=False)
    key = env.get("GEMINI_API_KEY", "")
    gemini: LLMClient | None = None
    if key not in _PLACEHOLDERS:
        from quarantix.ai.gemini import GeminiClient  # imported lazily: the SDK is slow to load

        gemini = GeminiClient(key)
    paid = wrap(gemini, paid=True) if gemini is not None or mode == "replay" else None

    naive_model = env.get("NAIVE_AGENT_MODEL", "gemini-3.1-flash-lite")
    reader_model = env.get("READER_MODEL", "gemini-3.1-flash-lite")
    economy = Brains(local, ollama_model, Reader(local, ollama_model), f"economy: {ollama_model}")
    if paid is not None:
        normal = Brains(paid, naive_model, Reader(paid, reader_model), naive_model)
    else:  # no paid key: the local model is the only baseline (said honestly on screen)
        normal = Brains(local, ollama_model, Reader(local, ollama_model), f"local: {ollama_model}")
    planner_model = env.get("PLANNER_MODEL", "gemini-3.8-flash")
    drafter_model = env.get("DRAFTER_MODEL", "gemini-3.8-flash")
    return Models(
        meter=meter,
        brains=BrainsSwitch(normal, economy, lambda: meter.economy),
        planner=(paid, planner_model) if paid is not None else None,
        drafter=(paid, drafter_model) if paid is not None else None,
        local=(local, ollama_model),
        mode=mode,
        closers=closers,
    )


def load_domains(env: Mapping[str, str] | None = None) -> dict[str, Domain]:
    env = os.environ if env is None else env
    root = Path(env.get("AGENTWALL_DOMAINS_DIR", str(REPO_ROOT / "domains")))
    return load_all(root) if root.is_dir() else {}


class AttackerLinks:
    """One shared HTTP client for every world's attacker link (2 s timeout)."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        env = os.environ if env is None else env
        self.base_url = env.get("AGENTWALL_ATTACKER_URL", "http://localhost:9000")
        self.client = httpx.AsyncClient(timeout=2.0)

    def __call__(self, domain: Domain) -> AttackerLink:
        markers = domain.attacker
        email_domain = markers.email.rsplit("@", 1)[-1] if "@" in markers.email else ""
        return AttackerLink(
            markers.hosts,
            email_domains=(email_domain,) if email_domain else (),
            deliver_to=self.base_url,
            client=self.client,
        )

    async def close(self) -> None:
        await self.client.aclose()
