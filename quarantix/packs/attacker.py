"""The only network path fake tools have: the local attacker server (contracts 10.3, 10.6).

Every attempt to reach an attacker address is recorded as a hit, the per-world
"attacker log" that goal checks read. Only attacker addresses are ever delivered,
through one shared HTTP client with a 2 s timeout, to the real attacker server so
its page lights up. Any other host is never contacted; the caller records it in a
ledger instead. Hosts are compared on the parsed host and port, so tricks like
`http://attacker:9000@evil.example/` count as evil.example.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

MAX_HITS = 500
MAX_BODY = 2000
TIMEOUT_S = 2.0


@dataclass(frozen=True, slots=True)
class AttackerHit:
    time: float
    method: str
    url: str
    path: str
    query: str
    body: str
    delivered: bool

    def text(self) -> str:
        """Everything the attacker received, as one string (for goal checks)."""
        return f"{self.method} {self.path}?{self.query}\n{self.body}"


def host_port(url: str) -> str | None:
    """`host:port` of an http(s) URL (default ports made explicit), or None."""
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return None
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError:
        return None
    return f"{parts.hostname.lower().rstrip('.')}:{port}"


class AttackerLink:
    def __init__(
        self,
        hosts: tuple[str, ...],
        *,
        email_domains: tuple[str, ...] = (),
        deliver_to: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.hosts = frozenset(_canonical_host(h) for h in hosts)
        self.email_domains = frozenset(d.lower() for d in email_domains)
        self.deliver_to = deliver_to.rstrip("/") if deliver_to else None
        self.client = client
        self.hits: deque[AttackerHit] = deque(maxlen=MAX_HITS)

    def fresh(self) -> AttackerLink:
        """Same configuration and shared client, empty log (one per world clone)."""
        link = AttackerLink.__new__(AttackerLink)
        link.hosts = self.hosts
        link.email_domains = self.email_domains
        link.deliver_to = self.deliver_to
        link.client = self.client
        link.hits = deque(maxlen=MAX_HITS)
        return link

    def is_attacker_url(self, url: str) -> bool:
        return host_port(url) in self.hosts

    def is_attacker_email(self, address: str) -> bool:
        if "@" not in address or "://" in address:
            return False
        domain = address.rsplit("@", 1)[1].strip().lower().rstrip(".")
        return domain in self.email_domains

    async def send(self, method: str, url: str, body: str = "") -> bool:
        """Deliver to the attacker server if `url` is an attacker address. Never anything else."""
        if not self.is_attacker_url(url):
            return False
        parts = urlsplit(url.strip())
        path = parts.path or "/"
        await self._record(method.upper(), url, path, parts.query, body)
        return True

    async def mail(self, to: str, body: str) -> bool:
        """An email to an attacker address is shown on the attacker page (no real mail)."""
        if not self.is_attacker_email(to):
            return False
        await self._record("MAIL", f"mailto:{to}", f"/_mail/{to}", "", body)
        return True

    async def _record(self, method: str, url: str, path: str, query: str, body: str) -> None:
        body = body[:MAX_BODY]
        delivered = False
        if self.client is not None and self.deliver_to is not None:
            target = f"{self.deliver_to}{path}" + (f"?{query}" if query else "")
            try:
                response = await self.client.request(
                    "POST" if method == "MAIL" else method, target, content=body, timeout=TIMEOUT_S
                )
                delivered = response.status_code < 500
            except httpx.HTTPError:
                delivered = False  # the attacker page being down never fails a tool call
        self.hits.append(AttackerHit(time.time(), method, url, path, query, body, delivered))


def _canonical_host(host: str) -> str:
    host = host.strip().lower()
    return host if ":" in host else f"{host}:80"
