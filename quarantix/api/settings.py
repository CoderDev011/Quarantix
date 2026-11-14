"""Control-plane settings, read from the environment (names match .env.example)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

BUNDLED_DASHBOARD = Path(__file__).resolve().parent / "static"  # where the image copies dist/
REPO_DOMAINS = Path(__file__).resolve().parents[2] / "domains"
_PLACEHOLDERS = frozenset({"", "replace-me"})  # the values .env.example ships with


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    admin_token: str
    agent_keys: Mapping[str, str] = field(default_factory=dict)  # agent name -> key
    long_poll_max_s: float = 25.0
    online_window_s: float = 35.0
    flush_interval: float = 0.1
    max_body_bytes: int = 1_000_000
    dashboard_dir: Path | None = None  # the built console (dashboard/dist); None = API only
    domains_dir: Path | None = None  # domain packs; None = no arena, no domain policies
    traces_dir: Path | None = None  # recorded tool-call traces for Autopilot proofs
    arena_workers: int = 2
    arena_queue_cap: int = 50
    arena_player_interval_s: float = 20.0

    def __post_init__(self) -> None:
        if len(self.admin_token) < 16:
            raise ValueError("the admin token must be at least 16 characters")
        for agent, key in self.agent_keys.items():
            if len(key) < 12:
                raise ValueError(f"the key for {agent!r} must be at least 12 characters")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        token = env.get("AGENTWALL_ADMIN_TOKEN", "")
        if token in _PLACEHOLDERS:
            raise ValueError("set AGENTWALL_ADMIN_TOKEN (no default: the console must not be open)")
        return cls(
            database_url=env.get("AGENTWALL_DB", "sqlite+aiosqlite:///data/quarantix.db"),
            admin_token=token,
            agent_keys=parse_agent_keys(env.get("AGENTWALL_AGENT_KEYS", "")),
            dashboard_dir=Path(env["AGENTWALL_DASHBOARD_DIR"])
            if env.get("AGENTWALL_DASHBOARD_DIR")
            else BUNDLED_DASHBOARD,
            domains_dir=Path(env.get("AGENTWALL_DOMAINS_DIR") or REPO_DOMAINS),
            traces_dir=Path(env["AGENTWALL_TRACES_DIR"])
            if env.get("AGENTWALL_TRACES_DIR")
            else None,
            arena_workers=int(env.get("ARENA_WORKERS", "2")),
            arena_queue_cap=int(env.get("ARENA_QUEUE_CAP", "50")),
            arena_player_interval_s=float(env.get("ARENA_SECONDS_BETWEEN_ATTEMPTS", "20")),
        )


def parse_agent_keys(text: str) -> dict[str, str]:
    """`agent-a:key1,agent-b:key2` -> {"agent-a": "key1", "agent-b": "key2"}."""
    keys: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in text.split(","))):
        agent, separator, key = item.partition(":")
        if not separator or not agent or not key:
            raise ValueError(f"invalid agent key entry {item.split(':')[0]!r}: use agent:key")
        keys[agent] = key
    return keys
