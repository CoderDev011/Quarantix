"""F13/F20 console support: typed responses (OpenAPI), cookie login, serving the built dashboard."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from quarantix.api.app import ADMIN_COOKIE, create_app
from quarantix.api.settings import Settings

TOKEN = "admin-token-for-tests"


async def _client(
    tmp_path: Path, dashboard: Path | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'c.db'}",
        admin_token=TOKEN,
        agent_keys={"agent-a": "key-for-agent-a"},
        dashboard_dir=dashboard,
    )
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def api(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    async for client in _client(tmp_path):
        yield client


@pytest.fixture
def built_dashboard(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>console</html>", encoding="utf-8")
    (root / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("do not serve", encoding="utf-8")
    return root


# ---------------------------------------------------------------- cookie login


async def test_a_valid_token_sets_an_httponly_strict_cookie(api: httpx.AsyncClient) -> None:
    response = await api.post("/v1/session", json={"token": TOKEN})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert f"{ADMIN_COOKIE}=" in cookie
    assert "httponly" in cookie.lower() and "samesite=strict" in cookie.lower()


async def test_the_cookie_then_authorizes_admin_routes(api: httpx.AsyncClient) -> None:
    await api.post("/v1/session", json={"token": TOKEN})
    assert (await api.get("/v1/agents")).status_code == 200  # no header: the cookie is enough


async def test_a_wrong_token_is_refused_and_sets_no_cookie(api: httpx.AsyncClient) -> None:
    response = await api.post("/v1/session", json={"token": "wrong-token-value"})
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_logging_out_clears_the_cookie(api: httpx.AsyncClient) -> None:
    await api.post("/v1/session", json={"token": TOKEN})
    await api.delete("/v1/session")
    assert (await api.get("/v1/agents")).status_code == 401


# ---------------------------------------------------------------- typed responses for generated TS types


async def test_openapi_describes_the_console_responses(api: httpx.AsyncClient) -> None:
    schemas = (await api.get("/openapi.json")).json()["components"]["schemas"]
    for name in (
        "EventOut",
        "EventsPage",
        "AgentOut",
        "AgentsPage",
        "ApprovalOut",
        "ApprovalsPage",
        "DecisionOut",
    ):
        assert name in schemas, name
    event = schemas["EventOut"]["properties"]
    assert {"seq", "event_id", "kind", "decision", "args", "outcome"} <= set(event)


# ---------------------------------------------------------------- serving the built dashboard


async def test_the_built_dashboard_is_served_with_an_spa_fallback(
    tmp_path: Path, built_dashboard: Path
) -> None:
    async for client in _client(tmp_path, built_dashboard):
        assert (await client.get("/")).text == "<html>console</html>"
        assert (await client.get("/arena/screen")).text == "<html>console</html>"
        asset = await client.get("/assets/app.js")
        assert asset.status_code == 200 and "console.log" in asset.text


async def test_api_paths_never_fall_back_to_the_dashboard(
    tmp_path: Path, built_dashboard: Path
) -> None:
    async for client in _client(tmp_path, built_dashboard):
        missing = await client.get("/v1/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["error"] == "not_found"


async def test_files_outside_the_dashboard_are_never_served(
    tmp_path: Path, built_dashboard: Path
) -> None:
    async for client in _client(tmp_path, built_dashboard):
        for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
            response = await client.get(path)
            assert "do not serve" not in response.text, path


async def test_without_a_build_the_root_says_how_to_build_it(api: httpx.AsyncClient) -> None:
    response = await api.get("/")
    assert response.status_code == 404
    assert "pnpm build" in response.json()["message"]
