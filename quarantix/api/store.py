"""Control-plane store (F13): SQLite in WAL mode via SQLAlchemy Core + aiosqlite.

Only previews are ever stored (the Gate redacts before an event leaves it).
Event inserts ignore duplicate event ids, so SDK retries are idempotent. Postgres
later is a URL change. All SQL is parameterized by SQLAlchemy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, Text, event, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from quarantix.core.contracts import Event

metadata = MetaData()

events_table = Table(
    "events",
    metadata,
    Column("seq", Integer, primary_key=True, autoincrement=False),
    Column("event_id", String, nullable=False, unique=True),
    Column("run_id", String, nullable=False),
    Column("agent", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("decision", String),
    Column("time", String, nullable=False),
    Column("body", Text, nullable=False),
)
policy_packs_table = Table(
    "policy_packs",
    metadata,
    Column("name", String, primary_key=True),
    Column("yaml", Text, nullable=False),
    Column("origin", String, nullable=False),
    Column("updated", String, nullable=False),
)

Index("ix_events_run", events_table.c.run_id)
Index("ix_events_agent_seq", events_table.c.agent, events_table.c.seq)
Index("ix_events_kind_seq", events_table.c.kind, events_table.c.seq)


class Store:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url)

        @event.listens_for(self.engine.sync_engine, "connect")
        def _pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    async def create(self) -> None:
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    async def journal_mode(self) -> str:
        async with self.engine.connect() as connection:
            result = await connection.exec_driver_sql("PRAGMA journal_mode")
            return str(result.scalar_one()).lower()

    async def insert_events(self, batch: Sequence[Event]) -> int:
        """Insert in one transaction. Returns how many were new (duplicates are ignored)."""
        if not batch:
            return 0
        rows = [
            {
                "seq": item.seq,
                "event_id": item.event_id,
                "run_id": item.run_id,
                "agent": item.agent,
                "kind": item.kind,
                "decision": item.decision.kind if item.decision is not None else None,
                "time": item.time.isoformat(),
                "body": json.dumps(item.to_wire(), separators=(",", ":"), default=str),
            }
            for item in batch
        ]
        statement = sqlite_insert(events_table).on_conflict_do_nothing(index_elements=["event_id"])
        async with self.engine.begin() as connection:
            result = await connection.execute(statement, rows)
        return max(result.rowcount, 0)

    async def events_since(
        self,
        since: int = 0,
        *,
        agent: str | None = None,
        run_id: str | None = None,
        kinds: Sequence[str] | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        query = select(events_table.c.body).where(events_table.c.seq > since)
        if agent is not None:
            query = query.where(events_table.c.agent == agent)
        if run_id is not None:
            query = query.where(events_table.c.run_id == run_id)
        if kinds:
            query = query.where(events_table.c.kind.in_(list(kinds)))
        query = query.order_by(events_table.c.seq).limit(limit)
        async with self.engine.connect() as connection:
            result = await connection.execute(query)
            return [json.loads(body) for (body,) in result.all()]

    async def save_pack(self, name: str, yaml_text: str, origin: str) -> None:
        statement = sqlite_insert(policy_packs_table).values(
            name=name, yaml=yaml_text, origin=origin, updated=datetime.now(UTC).isoformat()
        )
        statement = statement.on_conflict_do_update(
            index_elements=["name"],
            set_={"yaml": statement.excluded.yaml, "origin": statement.excluded.origin,
                  "updated": statement.excluded.updated},
        )  # fmt: skip
        async with self.engine.begin() as connection:
            await connection.execute(statement)

    async def load_packs(self) -> dict[str, str]:
        """Saved packs, name -> YAML text."""
        async with self.engine.connect() as connection:
            result = await connection.execute(
                select(policy_packs_table.c.name, policy_packs_table.c.yaml)
            )
            return {name: text for name, text in result.all()}

    async def max_seq(self) -> int:
        async with self.engine.connect() as connection:
            result = await connection.execute(select(func.max(events_table.c.seq)))
            return int(result.scalar_one() or 0)
