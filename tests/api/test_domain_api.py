"""F19 routes on the real app: generate -> review -> confirm -> goals in the arena."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from quarantix.api.app import create_app
from quarantix.api.settings import Settings
from quarantix.domaingen.generator import DomainGenerator
from tests.domaingen.test_generator import SEEDS, SKELETON, FakeGenerator
from tests.packs.conftest import DOMAINS

ADMIN = {"Authorization": "Bearer admin-token-for-tests"}


@pytest.fixture
async def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'd.db'}",
        admin_token="admin-token-for-tests",
        flush_interval=0.01,
        domains_dir=DOMAINS,
        drafts_dir=tmp_path / "drafts",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.domain_generator = DomainGenerator(
            FakeGenerator([SKELETON, SEEDS]), "m", tmp_path / "drafts"
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_generate_review_confirm(client: httpx.AsyncClient) -> None:
    assert (await client.post("/v1/domains/generate", json={"description": "x"})).status_code == 401
    made = await client.post(
        "/v1/domains/generate", headers=ADMIN, json={"description": "hospital patient records"}
    )
    assert made.status_code == 201
    draft = made.json()
    assert draft["status"] == "validated" and draft["changed_by_hardening"] > 0
    goals = (await client.get("/v1/arena/goals")).json()["goals"]
    assert "hospital_records" not in {g["domain"] for g in goals}  # nothing before confirm
    fetched = await client.get(f"/v1/domains/drafts/{draft['draft_id']}", headers=ADMIN)
    assert fetched.json()["name"] == "hospital_records"
    confirmed = await client.post(f"/v1/domains/drafts/{draft['draft_id']}/confirm", headers=ADMIN)
    assert confirmed.status_code == 200 and confirmed.json()["agent"] == "hospital-records-agent"
    goals = (await client.get("/v1/arena/goals")).json()["goals"]
    assert ("hospital_records", "money_to_attacker") in {(g["domain"], g["goal_id"]) for g in goals}
    packs = (await client.get("/v1/policies/packs", headers=ADMIN)).json()["packs"]
    assert "hospital_records" in {p["name"] for p in packs}


async def test_a_vague_description_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/v1/domains/generate", headers=ADMIN, json={"description": "stuff"}
    )
    assert response.status_code == 422 and response.json()["error"] == "generation_failed"


async def test_the_proof_wall_endpoint(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/proof")).status_code == 401
    report = (await client.get("/v1/proof", headers=ADMIN)).json()
    assert report["total"] >= 7 and report["failed"] == 0
    rw01 = next(s for s in report["scenarios"] if s["scenario_id"] == "RW-01")
    assert rw01["modes"]["guard"]["outcome"] == "succeeded"  # the honest day-one gap


async def test_the_results_endpoint_needs_admin(client: httpx.AsyncClient) -> None:
    assert (await client.get("/v1/redteam/latest")).status_code == 401
    response = await client.get("/v1/redteam/latest", headers=ADMIN)
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "metrics" in response.json() and "cases" not in response.json()
