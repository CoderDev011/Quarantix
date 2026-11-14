"""F13 HTTP API. Spec: docs/features/F13-control-plane.md (endpoints, auth, long-polls, errors)."""

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from quarantix.api.app import create_app, resume_point
from quarantix.api.settings import Settings
from quarantix.core.contracts import Decision, Event
from quarantix.engine.policy import PolicyBundle, compile_pack
from tests.engine._factories import arg, request

ADMIN = {"Authorization": "Bearer admin-token-for-tests"}
AGENT_A = {"Authorization": "Bearer key-for-agent-a"}
AGENT_B = {"Authorization": "Bearer key-for-agent-b"}

PACK = """\
schema_version: 1
pack: money
rules:
  - name: small-payments
    tool: pay
    when: [{arg: amount, value: {lte: 2000}}]
    decision: allow
"""


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        admin_token="admin-token-for-tests",
        agent_keys={"agent-a": "key-for-agent-a", "agent-b": "key-for-agent-b"},
        flush_interval=0.01,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.app = app  # type: ignore[attr-defined]
            yield client


def _event(n: int, agent: str = "agent-a") -> dict[str, Any]:
    return Event(
        event_id=f"e{n}",
        run_id="run-1",
        agent=agent,
        mode="guard",
        kind="tool.call",
        time=datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        tool="pay",
    ).to_wire()


# ---------------------------------------------------------------- health, auth and errors


async def test_health_needs_no_auth(api: httpx.AsyncClient) -> None:
    response = await api.get("/healthz")
    assert response.status_code == 200 and response.json()["status"] == "ok"


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": "key-for-agent-a"}]
)
async def test_agent_routes_reject_missing_or_wrong_keys(
    api: httpx.AsyncClient, headers: dict
) -> None:
    response = await api.post("/v1/events:batch", json={"events": []}, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


async def test_admin_routes_reject_agent_keys(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/events", headers=AGENT_A)
    assert response.status_code == 401


async def test_the_live_stream_needs_the_admin_token(api: httpx.AsyncClient) -> None:
    assert (await api.get("/v1/events/stream")).status_code == 401
    assert (await api.get("/v1/events/stream?token=wrong")).status_code == 401


def test_last_event_id_takes_precedence_over_since() -> None:
    assert resume_point(since=3, last_event_id="17") == 17
    assert resume_point(since=3, last_event_id=None) == 3
    assert resume_point(since=3, last_event_id="garbage") == 3


async def test_oversized_bodies_are_rejected(api: httpx.AsyncClient) -> None:
    response = await api.post("/v1/events:batch", content=b"x" * 1_000_001, headers=AGENT_A)
    assert response.status_code == 413
    assert response.json()["error"] == "too_large"


# ---------------------------------------------------------------- events


async def test_agents_upload_events_and_admins_read_history(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/v1/events:batch", json={"events": [_event(1), _event(2)]}, headers=AGENT_A
    )
    assert response.json() == {"accepted": 2, "duplicates": 0, "rejected": []}
    await api.app.state.bus.flush()  # type: ignore[attr-defined]
    history = (await api.get("/v1/events", headers=ADMIN)).json()
    assert [e["event_id"] for e in history["events"]] == ["e1", "e2"]
    assert [e["seq"] for e in history["events"]] == [1, 2]


async def test_a_retried_batch_is_not_stored_twice(api: httpx.AsyncClient) -> None:
    batch = {"events": [_event(1), _event(2)]}
    await api.post("/v1/events:batch", json=batch, headers=AGENT_A)
    again = (await api.post("/v1/events:batch", json=batch, headers=AGENT_A)).json()
    assert again == {"accepted": 0, "duplicates": 2, "rejected": []}
    await api.app.state.bus.flush()  # type: ignore[attr-defined]
    assert len((await api.get("/v1/events", headers=ADMIN)).json()["events"]) == 2


async def test_an_agent_cannot_upload_events_for_another_agent(api: httpx.AsyncClient) -> None:
    body = {"events": [_event(1), _event(2, agent="agent-b"), {"kind": "nonsense"}]}
    result = (await api.post("/v1/events:batch", json=body, headers=AGENT_A)).json()
    assert result["accepted"] == 1
    assert [r["index"] for r in result["rejected"]] == [1, 2]
    assert "agent" in result["rejected"][0]["error"]


async def test_batches_over_500_events_are_rejected(api: httpx.AsyncClient) -> None:
    body = {"events": [_event(i) for i in range(501)]}
    assert (await api.post("/v1/events:batch", json=body, headers=AGENT_A)).status_code == 413


async def test_history_filters_by_agent(api: httpx.AsyncClient) -> None:
    await api.post("/v1/events:batch", json={"events": [_event(1)]}, headers=AGENT_A)
    await api.post(
        "/v1/events:batch", json={"events": [_event(2, agent="agent-b")]}, headers=AGENT_B
    )
    await api.app.state.bus.flush()  # type: ignore[attr-defined]
    history = (await api.get("/v1/events?agent=agent-b", headers=ADMIN)).json()
    assert [e["agent"] for e in history["events"]] == ["agent-b"]


# ---------------------------------------------------------------- policy packs and bundle sync


async def test_a_valid_pack_is_saved_and_listed(api: httpx.AsyncClient) -> None:
    saved = await api.put("/v1/policies/packs/money", content=PACK, headers=ADMIN)
    assert saved.status_code == 200 and len(saved.json()["bundle_version"]) == 12
    listed = (await api.get("/v1/policies/packs", headers=ADMIN)).json()
    assert [p["name"] for p in listed["packs"]] == ["money"]
    assert (await api.get("/v1/policies/packs/money", headers=ADMIN)).text == PACK


async def test_an_invalid_pack_returns_its_line_and_is_not_saved(api: httpx.AsyncClient) -> None:
    broken = PACK.replace("lte: 2000", "about: 2000")
    response = await api.put("/v1/policies/packs/money", content=broken, headers=ADMIN)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_policy"
    assert body["details"]["line"] == 6
    assert (await api.get("/v1/policies/packs", headers=ADMIN)).json()["packs"] == []


async def test_the_path_name_must_match_the_pack_name(api: httpx.AsyncClient) -> None:
    response = await api.put("/v1/policies/packs/other", content=PACK, headers=ADMIN)
    assert response.status_code == 422


async def test_validate_compiles_without_saving(api: httpx.AsyncClient) -> None:
    assert (await api.post("/v1/policies/validate", content=PACK, headers=ADMIN)).json() == {
        "valid": True
    }
    assert (await api.get("/v1/policies/packs", headers=ADMIN)).json()["packs"] == []


async def test_agents_fetch_the_bundle_with_an_etag_and_get_304_when_unchanged(
    api: httpx.AsyncClient,
) -> None:
    await api.put("/v1/policies/packs/money", content=PACK, headers=ADMIN)
    first = await api.get("/v1/policies/bundle?agent=agent-a&wait=0", headers=AGENT_A)
    assert first.status_code == 200
    version = first.json()["version"]
    assert first.headers["etag"] == f'"{version}"'
    # The SDK can verify the bundle by recompiling it: same packs, same version.
    rebuilt = PolicyBundle(tuple(compile_pack(p["yaml"]) for p in first.json()["packs"]))
    assert rebuilt.version == version
    unchanged = await api.get(
        "/v1/policies/bundle?agent=agent-a&wait=0",
        headers={**AGENT_A, "If-None-Match": f'"{version}"'},
    )
    assert unchanged.status_code == 304


async def test_the_bundle_long_poll_returns_soon_after_a_change(api: httpx.AsyncClient) -> None:
    version = (await api.get("/v1/policies/bundle?agent=agent-a&wait=0", headers=AGENT_A)).json()[
        "version"
    ]

    async def change_soon() -> None:
        await asyncio.sleep(0.1)
        await api.put("/v1/policies/packs/money", content=PACK, headers=ADMIN)

    start = time.perf_counter()
    changer = asyncio.create_task(change_soon())
    response = await api.get(
        "/v1/policies/bundle?agent=agent-a&wait=5",
        headers={**AGENT_A, "If-None-Match": f'"{version}"'},
    )
    await changer
    elapsed = time.perf_counter() - start
    assert response.status_code == 200 and response.json()["version"] != version
    assert elapsed < 1.0


async def test_an_agent_can_only_sync_its_own_bundle(api: httpx.AsyncClient) -> None:
    response = await api.get("/v1/policies/bundle?agent=agent-b&wait=0", headers=AGENT_A)
    assert response.status_code == 403


# ---------------------------------------------------------------- agents and modes


async def test_syncing_marks_an_agent_online(api: httpx.AsyncClient) -> None:
    before = {a["name"]: a for a in (await api.get("/v1/agents", headers=ADMIN)).json()["agents"]}
    assert before["agent-a"]["online"] is False
    await api.get(
        "/v1/policies/bundle?agent=agent-a&wait=0", headers={**AGENT_A, "X-Quarantix-SDK": "0.1.0"}
    )
    after = {a["name"]: a for a in (await api.get("/v1/agents", headers=ADMIN)).json()["agents"]}
    assert after["agent-a"]["online"] is True
    assert after["agent-a"]["sdk_version"] == "0.1.0"
    assert after["agent-b"]["online"] is False


async def test_changing_an_agents_mode_bumps_the_bundle(api: httpx.AsyncClient) -> None:
    old = (await api.get("/v1/policies/bundle?agent=agent-a&wait=0", headers=AGENT_A)).json()[
        "version"
    ]
    assert (
        await api.put("/v1/agents/agent-a/mode", json={"mode": "monitor"}, headers=ADMIN)
    ).status_code == 200
    bundle = (await api.get("/v1/policies/bundle?agent=agent-a&wait=0", headers=AGENT_A)).json()
    assert bundle["version"] != old
    compiled = PolicyBundle(tuple(compile_pack(p["yaml"]) for p in bundle["packs"]))
    assert compiled.for_agent("agent-a").mode == "monitor"
    assert compiled.for_agent("agent-b").mode == "enforce"
    agents = {a["name"]: a for a in (await api.get("/v1/agents", headers=ADMIN)).json()["agents"]}
    assert agents["agent-a"]["mode"] == "monitor"


@pytest.mark.parametrize(("agent", "mode"), [("agent-a", "loud"), ("Bad Name!", "monitor")])
async def test_invalid_modes_and_agent_names_are_rejected(
    api: httpx.AsyncClient, agent: str, mode: str
) -> None:
    response = await api.put(f"/v1/agents/{agent}/mode", json={"mode": mode}, headers=ADMIN)
    assert response.status_code == 422


# ---------------------------------------------------------------- approvals inbox


async def test_admins_list_and_resolve_pending_approvals(api: httpx.AsyncClient) -> None:
    broker = api.app.state.approvals  # type: ignore[attr-defined]
    call = request("pay", account=arg("ACC-1"), amount=arg(5000))
    decision = Decision(
        "ask", "core/C3-untrusted-context-high-risk", "A person should approve.", "v1"
    )
    approval_id = await broker.open(call, decision)
    waiting = asyncio.create_task(broker.wait(approval_id, 5))

    pending = (await api.get("/v1/approvals", headers=ADMIN)).json()["approvals"]
    assert [(p["id"], p["tool"], p["rule"]) for p in pending] == [
        (approval_id, "pay", decision.rule)
    ]
    assert pending[0]["args"]["amount"]["preview"] == "5000"

    resolved = await api.post(
        f"/v1/approvals/{approval_id}/resolve", json={"verdict": "approve"}, headers=ADMIN
    )
    assert resolved.status_code == 200
    assert (await waiting).status == "approved"
    again = await api.post(
        f"/v1/approvals/{approval_id}/resolve", json={"verdict": "deny"}, headers=ADMIN
    )
    assert again.status_code == 409
    assert again.json()["error"] == "conflict"
