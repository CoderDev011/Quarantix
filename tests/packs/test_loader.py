"""F03 pack loader. Spec: docs/features/F03-domain-packs.md, contracts section 10."""

from __future__ import annotations

import gc
import statistics
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from quarantix.core.labels import Confidentiality, Integrity
from quarantix.core.plan_validate import validate_plan
from quarantix.core.registry import ChannelAllowlist
from quarantix.packs.loader import PackError, load_all, load_domain
from quarantix.packs.model import Domain
from tests.packs.conftest import DOMAINS

EditPack = Callable[..., Path]


def test_all_packs_load_and_their_pinned_plans_validate() -> None:
    domains = load_all(DOMAINS)
    assert {"support", "devops"} <= set(domains)
    for domain in domains.values():
        for plan in domain.plans.values():
            assert validate_plan(plan, domain.registry) == []
        assert domain.goals and domain.tasks


def test_outsider_text_is_labeled_untrusted_and_ids_trusted(support: Domain) -> None:
    spec = support.registry.get("list_tickets")
    assert spec.field_labels["text"].integrity is Integrity.UNTRUSTED
    assert spec.field_labels["text"].confidentiality is Confidentiality.PRIVATE
    assert spec.output_label.integrity is Integrity.TRUSTED  # ids and customer ids
    assert "customer_id" not in spec.field_labels


def test_tool_metadata_comes_from_the_manifest(support: Domain, devops: Domain) -> None:
    refund = support.registry.get("issue_refund")
    assert (refund.kind, refund.risk, refund.audience) == ("sink", "high", "internal")
    assert set(refund.critical_args) == {"order_number", "amount"}
    post = support.registry.get("post_message")
    assert isinstance(post.audience, ChannelAllowlist)
    assert post.audience.known == {"#support-log", "#support-team"}
    assert support.registry.get("get_order").endorses_output
    assert devops.registry.get("read_secret").output_label.confidentiality is Confidentiality.SECRET


def test_validation_rejects_an_outsider_text_field_labeled_trusted(edit_pack: EditPack) -> None:
    root = edit_pack(
        "support",
        {
            "    behavior: list_records\n": (
                "    behavior: list_records\n"
                "    field_labels: {text: {integrity: trusted, confidentiality: private}}\n"
            )
        },
    )
    with pytest.raises(PackError) as error:
        load_domain(root)
    message = str(error.value)
    assert "list_tickets" in message and "'text'" in message and "untrusted" in message
    assert error.value.line is not None


def test_validation_rejects_a_money_argument_that_is_not_critical(edit_pack: EditPack) -> None:
    root = edit_pack(
        "support", {"critical_args: [order_number, amount]": "critical_args: [order_number]"}
    )
    with pytest.raises(PackError, match="money-like argument 'amount' must be critical"):
        load_domain(root)


def test_validation_rejects_a_destination_that_is_not_critical(edit_pack: EditPack) -> None:
    root = edit_pack("support", {"critical_args: [url]": "critical_args: [body]"})
    with pytest.raises(PackError, match="destination"):
        load_domain(root)


def test_validation_rejects_a_low_risk_sink(edit_pack: EditPack) -> None:
    root = edit_pack("support", {"    risk: medium\n": "    risk: low\n"})
    with pytest.raises(PackError, match="risk medium or high"):
        load_domain(root)


def test_validation_rejects_an_unknown_behavior_with_its_line(edit_pack: EditPack) -> None:
    root = edit_pack("support", {"behavior: send_external": "behavior: teleport"})
    with pytest.raises(PackError, match="unknown behavior 'teleport'") as error:
        load_domain(root)
    assert error.value.line is not None and error.value.line > 1


def test_validation_rejects_a_real_looking_email_in_seed(edit_pack: EditPack) -> None:
    root = edit_pack("support", {"ana@example.com": "ana@gmail.com"}, file="seed/customers.json")
    with pytest.raises(PackError, match="not a reserved fake domain"):
        load_domain(root)


def test_validation_rejects_a_goal_on_an_unknown_ledger(edit_pack: EditPack) -> None:
    root = edit_pack("support", {"ledgers: [refunds]": "ledgers: [payouts]"})
    with pytest.raises(PackError, match="unknown ledger 'payouts'"):
        load_domain(root)


def test_validation_rejects_a_missing_plant_target(edit_pack: EditPack) -> None:
    root = edit_pack(
        "support", {"      field: text\n      defaults": "      field: body\n      defaults"}
    )
    with pytest.raises(PackError, match=r"plant target tickets\.body does not exist"):
        load_domain(root)


def test_validation_rejects_a_pinned_plan_that_fails_the_validator(edit_pack: EditPack) -> None:
    root = edit_pack(
        "support",
        {'"tool": "issue_refund"': '"tool": "wire_money"'},
        file="plans/process-tickets.json",
    )
    with pytest.raises(PackError, match="unknown tool 'wire_money'"):
        load_domain(root)


def test_capability_index(support: Domain, devops: Domain) -> None:
    assert {"money_sink", "post_internal", "exfil_sink"} <= support.capabilities
    assert "read_secret" not in support.capabilities
    assert {"read_secret", "exfil_sink"} <= devops.capabilities
    assert "money_sink" not in devops.capabilities


def test_attacks_and_benign_tasks_load(support: Domain, devops: Domain) -> None:
    assert len(support.attacks) >= 5 and len(devops.attacks) >= 3
    assert all(a.goal_id in support.goals and a.task_id in support.tasks for a in support.attacks)
    assert len(support.benign) >= 2 and len(devops.benign) >= 2
    hidden = next(a for a in support.attacks if a.technique == "hidden_text")
    assert "​" in hidden.plant.payload  # YAML escapes become the real characters


@pytest.mark.perf
def test_perf_loading_a_pack_under_200_ms() -> None:
    timings = []
    for _ in range(5):
        gc.collect()
        start = time.perf_counter()
        load_domain(DOMAINS / "devops")  # the larger pack (200 log lines)
        timings.append((time.perf_counter() - start) * 1000)
    median = statistics.median(timings)
    print(f"\nload devops pack: median {median:.1f} ms")
    assert median < 200
