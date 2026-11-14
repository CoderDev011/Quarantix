"""Authentication (F13): agent keys and the admin token.

Only sha256 digests of secrets are kept in memory, and comparisons are constant
time. The key decides the agent's name: a request body can never claim to be
another agent.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping


def _digest(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


class Credentials:
    def __init__(self, admin_token: str, agent_keys: Mapping[str, str]) -> None:
        self._admin = _digest(admin_token)
        self._agents = [(agent, _digest(key)) for agent, key in agent_keys.items()]

    @property
    def agents(self) -> list[str]:
        return [agent for agent, _ in self._agents]

    def is_admin(self, token: str | None) -> bool:
        return token is not None and hmac.compare_digest(_digest(token), self._admin)

    def agent_for(self, key: str | None) -> str | None:
        if key is None:
            return None
        candidate = _digest(key)
        found = None
        for agent, digest in self._agents:  # check every entry: no early exit to time
            if hmac.compare_digest(candidate, digest):
                found = agent
        return found


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None
