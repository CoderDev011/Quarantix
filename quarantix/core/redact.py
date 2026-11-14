"""Argument previews and secret scrubbing (docs/contracts.md section 8).

Previews are what events, logs and screens may show of an argument: scrubbed
first, then truncated to 40 characters. A secret-labeled value is never
previewed at all. Every preview carries a sha256 digest of the full value so
two events can be compared without storing the value itself.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from agentwall.core.labels import Confidentiality, Label

MASK = "«masked»"
PREVIEW_LIMIT = 40

_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"-----BEGIN [A-Z ]+-----[\s\S]*?-----END [A-Z ]+-----",  # PEM blocks
        r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b",  # AWS access key ids
        r"\bsk-[A-Za-z0-9_-]{20,}",  # common API keys
        r"\bAIza[0-9A-Za-z_-]{30,}",  # Google API keys
        r"\bgh[pousr]_[A-Za-z0-9]{30,}",  # GitHub tokens
        r"\bxox[abposr]-[A-Za-z0-9-]{10,}",  # Slack tokens
        r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",  # JWTs
        r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b",  # IBAN-like accounts
    )
)
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def scrub(text: str) -> tuple[str, bool]:
    """Mask secret-shaped substrings. Returns the text and whether anything changed."""
    changed = False
    for pattern in _PATTERNS:
        text, count = pattern.subn(MASK, text)
        changed = changed or count > 0

    def mask_card(match: re.Match[str]) -> str:
        nonlocal changed
        digits = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            changed = True
            return MASK
        return match.group(0)

    return _CARD_CANDIDATE.sub(mask_card, text), changed


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def preview(value: Any, label: Label, evidence: str) -> dict[str, Any]:
    """The contract's argument preview: {preview, label, evidence, sha256, redacted}."""
    full = canonical(value)
    digest = hashlib.sha256(full.encode()).hexdigest()
    text = value if isinstance(value, str) else full
    if label.confidentiality is Confidentiality.SECRET:
        shown, redacted = f"[secret · {len(text)} chars]", True
    else:
        shown, redacted = scrub(text)
        if len(shown) > PREVIEW_LIMIT:
            shown = shown[: PREVIEW_LIMIT - 1] + "…"
    return {
        "preview": shown,
        "label": label.to_wire(),
        "evidence": evidence,
        "sha256": digest,
        "redacted": redacted,
    }
