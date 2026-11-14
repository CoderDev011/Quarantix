"""F12 SDK against the real control plane (in-process). Spec: docs/features/F12-sdk.md."""

import asyncio
import inspect
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from quarantix.api.app import create_app
from quarantix.api.settings import Settings
from quarantix.engine.gate import ToolBlocked
from quarantix.packs.loader import load_domain
from quarantix.packs.world import World
from quarantix.sdk import Quarantix
from tests.packs.conftest import DOMAINS

ADMIN = {"Authorization": "Bearer admin-token-for-tests"}
KEY = "key-for-support-agent"
OFFLINE = "runtime/offline-no-approver"
BLOCK_REFUNDS = """\
schema_version: 1
pack: emergency
applies_to: [support-agent]
rules:
  - {name: no-refunds-today, tool: issue_refund, decision: block, reason: Refunds are paused.}
"""


class Switch(httpx.AsyncBaseTransport):
    """The real app, with a network cable we can pull."""

    def __init__(self, app: Any) -> None:
        self.inner = httpx.ASGITransport(app=app)
        self.down = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("network down", request=request)
        return await self.inner.handle_async_request(request)


@pytest.fixture
async def plane(tmp_path: Path) -> AsyncIterator[tuple[Any, Switch, httpx.AsyncClient]]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'sdk.db'}",
        admin_token="admin-token-for-tests",
        agent_keys={"support-agent": KEY},
        flush_interval=0.01,
    )
    app = create_app(settings)
    support = load_domain(DOMAINS / "support")
    async with app.router.lifespan_context(app):
        switch = Switch(app)
        admin = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        await admin.put("/v1/policies/packs/support", headers=ADMIN, content=support.policy_text)
        yield app, switch, admin
        await admin.aclose()


def sdk_for(switch: httpx.AsyncBaseTransport, tmp_path: Path, world: World, **kw: Any) -> Quarantix:
    return Quarantix(
        api_key=KEY, agent="support-agent", url="http://test", registry=world.registry,
        cache_dir=tmp_path / "cache", transport=switch, **kw,
    )  # fmt: skip


def tool_fns(world: World) -> list[Any]:
    return [fn for n in world.registry.names() if (fn := world.registry.get(n).fn) is not None]


def support_world() -> World:
    return load_domain(DOMAINS / "support").world()


async def genuine_refund(qx: Quarantix, world: World) -> Any:
    tools = {fn.__name__: fn for fn in qx.wrap(tool_fns(world))}
    async with qx.session("Process today's new tickets and refund eligible orders."):
        await tools["list_tickets"](status="new")
        order = await tools["get_order"](order_number="ORD-1001", customer_id="C-1")
        return await tools["issue_refund"](
            order_number=order["order_number"], amount=order["amount"]
        )


async def test_wrapped_function_keeps_its_signature(tmp_path: Path) -> None:
    world = support_world()
    qx = sdk_for(httpx.MockTransport(lambda r: httpx.Response(503)), tmp_path, world)
    original = world.registry.get("issue_refund").fn

    async def issue_refund(order_number: str, amount: float = 0.0) -> str:
        """Refund an order."""
        return "ok"

    def sync_tool(a: int, *, b: str = "x") -> int:
        return a

    wrapped_async, wrapped_sync = qx.wrap([issue_refund, sync_tool])
    assert inspect.signature(wrapped_async) == inspect.signature(issue_refund)
    assert wrapped_async.__name__ == "issue_refund" and wrapped_async.__doc__ == "Refund an order."
    assert inspect.iscoroutinefunction(wrapped_async)
    assert inspect.signature(wrapped_sync) == inspect.signature(sync_tool)
    assert original is not None


async def test_online_genuine_refund_and_events_reach_the_console(
    plane: Any, tmp_path: Path
) -> None:
    _, switch, admin = plane
    world = support_world()
    async with sdk_for(switch, tmp_path, world) as qx:
        assert await qx.sync_now()
        assert await genuine_refund(qx, world) == "ok"
        assert qx.online and qx.status()["version"] == qx.bundle.version  # type: ignore[union-attr]
    events: dict[str, Any] = {}
    for _ in range(100):  # the bus writes to the store in batches
        events = (
            await admin.get("/v1/events", headers=ADMIN, params={"agent": "support-agent"})
        ).json()
        if len(events["events"]) >= 3:
            break
        await asyncio.sleep(0.02)
    tools = [e["tool"] for e in events["events"]]
    assert tools == ["list_tickets", "get_order", "issue_refund"]
    assert world.ledgers["refunds"] == [{"order_number": "ORD-1001", "amount": 120.0}]


async def test_a_policy_change_applies_in_under_a_second(plane: Any, tmp_path: Path) -> None:
    _, switch, admin = plane
    world = support_world()
    async with sdk_for(switch, tmp_path, world) as qx:
        for _ in range(100):  # the first sync happens right after start
            if qx.bundle is not None:
                break
            await asyncio.sleep(0.01)
        before = qx.bundle.version  # type: ignore[union-attr]
        await asyncio.sleep(0.05)  # let the long-poll park
        start = time.perf_counter()
        changed = await admin.put(
            "/v1/policies/packs/emergency", headers=ADMIN, content=BLOCK_REFUNDS
        )
        new_version = changed.json()["bundle_version"]
        while qx.bundle.version != new_version:  # type: ignore[union-attr]
            assert time.perf_counter() - start < 1.0, "the change did not arrive within 1 s"
            await asyncio.sleep(0.005)
        elapsed = time.perf_counter() - start
        print(f"\npolicy change reached the SDK in {elapsed * 1000:.0f} ms")
        assert new_version != before
        with pytest.raises(ToolBlocked) as blocked:
            await genuine_refund(qx, world)
        assert blocked.value.decision.rule == "emergency/no-refunds-today"


async def test_offline_uses_the_cached_bundle(plane: Any, tmp_path: Path) -> None:
    _, switch, _ = plane
    async with sdk_for(switch, tmp_path, support_world()) as qx:
        await qx.sync_now()
        cached = qx.bundle.version  # type: ignore[union-attr]
    switch.down = True
    world = support_world()
    qx = sdk_for(switch, tmp_path, world)  # a restart while the control plane is down
    assert qx.bundle is not None and qx.bundle.version == cached
    assert not qx.online
    assert await genuine_refund(qx, world) == "ok"  # decided locally by the cached pack


async def test_offline_an_ask_becomes_a_block(plane: Any, tmp_path: Path) -> None:
    _, switch, _ = plane
    async with sdk_for(switch, tmp_path, support_world()) as qx:
        await qx.sync_now()
    switch.down = True
    world = support_world()
    qx = sdk_for(switch, tmp_path, world)
    tools = {fn.__name__: fn for fn in qx.wrap(tool_fns(world))}
    async with qx.session("Process today's tickets."):
        await tools["list_tickets"](status="new")
        with pytest.raises(ToolBlocked) as blocked:
            await tools["send_webhook"](url="https://partner.example/n", body="hi")
    assert blocked.value.decision.rule == OFFLINE


async def test_cold_offline_blocks_high_risk_sinks(tmp_path: Path) -> None:
    world = support_world()
    down = httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down", request=r))
    )
    qx = sdk_for(down, tmp_path, world)
    assert qx.bundle is None
    tools = {fn.__name__: fn for fn in qx.wrap(tool_fns(world))}
    async with qx.session("Post a hello to #support-log"):
        assert (
            await tools["post_message"](channel="#support-log", text="hello") == "posted"
        )  # medium
        with pytest.raises(ToolBlocked) as blocked:
            await tools["issue_refund"](order_number="ORD-1001", amount=120.0)  # high risk
    assert blocked.value.decision.rule == "_failsafe/failsafe-issue_refund"


async def test_a_stale_bundle_blocks_high_risk_sinks(plane: Any, tmp_path: Path) -> None:
    _, switch, _ = plane
    async with sdk_for(switch, tmp_path, support_world()) as qx:
        await qx.sync_now()
    cache = tmp_path / "cache" / "bundle.json"
    data = json.loads(cache.read_text())
    data["fetched_at"] -= 25 * 3600
    cache.write_text(json.dumps(data))
    switch.down = True
    world = support_world()
    qx = sdk_for(switch, tmp_path, world)
    assert qx.bundle_age_s is not None and qx.bundle_age_s > 24 * 3600
    with pytest.raises(ToolBlocked):
        await genuine_refund(qx, world)


async def test_a_corrupted_cache_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "bundle.json").write_text("{not json")
    qx = sdk_for(httpx.MockTransport(lambda r: httpx.Response(503)), tmp_path, support_world())
    assert qx.bundle is None and "corrupted" in qx.warnings[0]


async def test_a_tampered_cache_is_refused(plane: Any, tmp_path: Path) -> None:
    _, switch, _ = plane
    async with sdk_for(switch, tmp_path, support_world()) as qx:
        await qx.sync_now()
    cache = tmp_path / "cache" / "bundle.json"
    data = json.loads(cache.read_text())
    data["packs"][0]["yaml"] = data["packs"][0]["yaml"].replace("2000", "999999")
    cache.write_text(json.dumps(data))
    qx = sdk_for(switch, tmp_path, support_world())
    assert qx.bundle is None and qx.warnings


async def test_events_buffer_while_offline_and_flush_on_reconnect(
    plane: Any, tmp_path: Path
) -> None:
    _, switch, admin = plane
    world = support_world()
    qx = sdk_for(switch, tmp_path, world)
    async with qx:
        await qx.sync_now()
        switch.down = True
        await genuine_refund(qx, world)  # decided locally; events wait in the buffer
        await asyncio.sleep(0.4)
        assert len(qx.events.buffer) == 3 and qx.events.sent == 0
        switch.down = False
        for _ in range(300):
            if qx.events.sent == 3:
                break
            await asyncio.sleep(0.05)
    assert qx.events.sent == 3
    events: dict[str, Any] = {}
    for _ in range(100):
        events = (
            await admin.get("/v1/events", headers=ADMIN, params={"agent": "support-agent"})
        ).json()
        if len(events["events"]) >= 3:
            break
        await asyncio.sleep(0.02)
    assert len(events["events"]) == 3


async def test_an_ask_goes_to_a_person_through_the_console(plane: Any, tmp_path: Path) -> None:
    _app, switch, admin = plane
    world = support_world()
    async with sdk_for(switch, tmp_path, world) as qx:
        await qx.sync_now()
        tools = {fn.__name__: fn for fn in qx.wrap(tool_fns(world))}

        async def approve_when_asked() -> None:
            for _ in range(200):
                pending = (await admin.get("/v1/approvals", headers=ADMIN)).json()["approvals"]
                if pending:
                    await admin.post(
                        f"/v1/approvals/{pending[0]['id']}/resolve", headers=ADMIN,
                        json={"verdict": "approve"},
                    )  # fmt: skip
                    return
                await asyncio.sleep(0.02)

        helper = asyncio.create_task(approve_when_asked())
        async with qx.session("Process today's tickets."):
            await tools["list_tickets"](status="new")
            sent = await tools["send_webhook"](url="https://partner.example/n", body="hi")
        await helper
    assert sent == "sent" and len(world.ledgers["outbox"]) == 1
