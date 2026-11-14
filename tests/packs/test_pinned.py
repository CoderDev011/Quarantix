"""F03 "done when": pinned plans run through the real Gate, benign tasks pass, attacks fail."""

from __future__ import annotations

import pytest

from quarantix.packs import harness
from quarantix.packs.goals import check_expected, check_goals
from quarantix.packs.model import Domain
from tests.packs._reader import HonestReader


async def run(domain: Domain, item: object = None) -> tuple[harness.Setup, str | None]:
    world = domain.world()
    harness.plant(world, item)  # type: ignore[arg-type]
    s = harness.setup(world)
    task_id = getattr(item, "task_id", None) or next(iter(domain.tasks))
    result = await harness.run_pinned(s, task_id, HonestReader())
    return s, result.answer


async def test_support_benign_run_refunds_only_eligible_orders(support: Domain) -> None:
    s, answer = await run(support)
    assert s.world.ledgers["refunds"] == [
        {"order_number": "ORD-1001", "amount": 120.0},
        {"order_number": "ORD-1003", "amount": 89.99},
        {"order_number": "ORD-1007", "amount": 640.0},
    ]
    assert s.world.ledgers["messages"][0]["channel"] == "#support-log"
    assert answer and "Refunded ORD-1001" in answer
    assert harness.summary(s)["blocks"] == 0 and harness.summary(s)["asks"] == 0


async def test_devops_benign_run_restarts_the_unhealthy_service(devops: Domain) -> None:
    s, answer = await run(devops)
    assert s.world.ledgers["restarts"] == [{"service": "api"}]
    assert answer == "Checked api: healthy=False"
    assert harness.summary(s)["blocks"] == 0


@pytest.mark.parametrize("name", ["support", "devops"])
async def test_every_benign_task_meets_its_expectations(
    name: str, support: Domain, devops: Domain
) -> None:
    domain = {"support": support, "devops": devops}[name]
    for task in domain.benign:
        s, answer = await run(domain, task)
        ok, failures = check_expected(task.expected, s.world, answer, len(s.recorder.blocks()))
        assert ok, (task.id, failures)


@pytest.mark.parametrize("name", ["support", "devops"])
async def test_no_library_attack_breaches_full_mode(
    name: str, support: Domain, devops: Domain
) -> None:
    domain = {"support": support, "devops": devops}[name]
    for attack in domain.attacks:
        s, answer = await run(domain, attack)
        hits = [r for r in check_goals(s.world, answer) if r.breached]
        assert hits == [], (attack.id, hits)
