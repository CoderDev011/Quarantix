"""Regenerate domains/devops/seed/logs.json (200 fake log lines, fixed seed).

uv run python scripts/gen_devops_seed.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SERVICES = ("api", "worker", "web", "cache")
INFO = {
    "api": ["GET /v1/orders 200 in {ms} ms", "POST /v1/session 201 in {ms} ms", "health check ok"],
    "worker": ["job {n} finished in {ms} ms", "picked up batch {n}", "queue depth {n}"],
    "web": ["served /index.html in {ms} ms", "cache hit ratio 0.{n}", "asset bundle reloaded"],
    "cache": ["evicted {n} keys", "memory at {n} MB", "replica in sync"],
}
ERRORS = {
    "api": [
        "upstream timeout after {ms} ms calling db-primary.company.example",
        "5xx rate {n}% over the last 5 minutes",
        "connection pool exhausted (max 64)",
    ],
    "worker": ["job {n} failed: retrying (attempt 2 of 3)"],
    "web": ["slow render on /checkout: {ms} ms"],
    "cache": ["replica lag {n} s"],
}


def main() -> None:
    rng = random.Random(20261114)  # noqa: S311 (fake seed data, not security)
    rows = []
    for i in range(1, 201):
        service = SERVICES[i % 4] if i < 170 else "api"  # the incident: api errors at the end
        failing = service == "api" and i >= 170
        level = "error" if failing or rng.random() < 0.05 else "info"
        pool = ERRORS[service] if level == "error" else INFO[service]
        text = rng.choice(pool).format(ms=rng.randint(12, 4800), n=rng.randint(2, 99))
        rows.append({"id": f"L-{i:03d}", "service": service, "level": level, "text": text})
    path = Path(__file__).resolve().parent.parent / "domains/devops/seed/logs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[\n" + ",\n".join("  " + json.dumps(r) for r in rows) + "\n]\n")
    print(f"wrote {len(rows)} lines to {path}")


if __name__ == "__main__":
    main()
