"""Previews and redaction. Spec: docs/contracts.md section 8, docs/features/F05-gate.md."""

import pytest

from quarantix.core.labels import Confidentiality, trusted, untrusted
from quarantix.core.redact import MASK, preview, scrub

INTERNAL = trusted("user")


def test_secret_values_are_never_previewed() -> None:
    result = preview("AKIAFAKEFAKEFAKE1234", trusted("system", Confidentiality.SECRET), "exact")
    assert result["preview"] == "[secret · 20 chars]"
    assert result["redacted"] is True
    assert "AKIA" not in str(result)


def test_previews_are_truncated_to_40_characters() -> None:
    result = preview("x" * 100, INTERNAL, "exact")
    assert len(result["preview"]) <= 40
    assert result["redacted"] is False


def test_preview_carries_label_evidence_and_a_digest_of_the_full_value() -> None:
    first = preview({"b": 2, "a": 1}, untrusted("tool:read#R-1"), "traced")
    second = preview({"a": 1, "b": 2}, untrusted("tool:read#R-1"), "traced")
    assert first["sha256"] == second["sha256"]  # canonical: key order does not matter
    assert len(first["sha256"]) == 64
    assert first["evidence"] == "traced"
    assert first["label"]["integrity"] == "untrusted"


@pytest.mark.parametrize(
    "secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "sk-abcdefghijklmnopqrstuvwxyz123456",
        "AIzaSyA1234567890abcdefghijklmnopqrstu",
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "xoxb-1234567890-abcdefghijkl",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abc123def456ghi789",
        "4111 1111 1111 1111",
        "GB82 WEST 1234 5698 7654 32",
    ],
)
def test_known_secret_shapes_are_masked(secret: str) -> None:
    masked, changed = scrub(f"key={secret} end")
    assert secret not in masked
    assert MASK in masked
    assert changed


def test_pem_blocks_are_masked() -> None:
    pem = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----"
    masked, changed = scrub(f"cert: {pem}")
    assert "MIIEvQ" not in masked
    assert changed


def test_numbers_that_fail_the_luhn_check_are_left_alone() -> None:
    masked, changed = scrub("order total 4111 1111 1111 1112")
    assert masked == "order total 4111 1111 1111 1112"
    assert not changed


def test_scrubbing_happens_before_truncation() -> None:
    result = preview("token sk-abcdefghijklmnopqrstuvwxyz123456 trailing text", INTERNAL, "exact")
    assert "sk-abc" not in result["preview"]
    assert result["redacted"] is True
