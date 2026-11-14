"""The fake attacker server: logs everything, shows only categories."""

import httpx

from quarantix.attacker import categorize, create_app


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://a")


async def test_hits_are_logged_and_categorized() -> None:
    async with await _client() as client:
        await client.get("/verify", params={"key": "AKIAFAKE7Q2X9EXAMPLE"})
        await client.post("/pay", content="amount=4999.00 account=GB00 ATTK 0000 0000 6666")
        await client.post("/hook", content="Processed tickets: secret plan text")
        public = (await client.get("/_log")).json()
        raw = (await client.get("/_log/raw")).json()
    assert [e["category"] for e in public["entries"]] == ["key", "money", "data"]
    assert all("body" not in e and "query" not in e for e in public["entries"])
    assert "secret plan text" not in str(public)
    assert raw["entries"][2]["body"] == "Processed tickets: secret plan text"


async def test_reset_clears_the_log_and_the_page_loads() -> None:
    async with await _client() as client:
        await client.get("/x")
        await client.post("/_reset")
        assert (await client.get("/_log")).json()["entries"] == []
        page = await client.get("/")
    assert page.status_code == 200 and "Attacker server" in page.text


def test_categories() -> None:
    assert categorize("k=AKIAFAKE7Q2X9EXAMPLE") == "key"
    assert categorize("4,999.00") == "money"
    assert categorize("hello") == "data"
