"""Arena heuristics (F15): technique tags and the nickname filter. No LLM involved."""

from __future__ import annotations

import random
import re
import unicodedata

MAX_NICKNAME = 20
_BASE64_RUN = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_HEX_RUN = re.compile(r"\b(?:0x)?[0-9a-fA-F]{32,}\b")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_ZERO_WIDTH = re.compile("[​-‏⁠﻿]")
_FAKE_SYSTEM = re.compile(
    r"\b(system\s*:|\[system|ignore (all |the )?(previous|prior|above)|new instructions|"
    r"developer (mode|message)|you are now|override)",
    re.IGNORECASE,
)
_AUTHORITY = re.compile(
    r"\b(ceo|cfo|cto|admin(istrator)?|urgent|immediately|security team|it department|"
    r"compliance|legal|pre-?approved|manager|boss)\b",
    re.IGNORECASE,
)
_SPLIT = re.compile(
    r"\b(previous|earlier|other|next|following|first|second) (message|ticket|email|line|log|note)\b"
    r"|\bpart [12]\b|\bsee (above|below)\b",
    re.IGNORECASE,
)
_NICK_ALLOWED = re.compile(r"[^\w .\-]", re.UNICODE)
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)
_BLOCKED = (
    "fuck", "shit", "bitch", "cunt", "dick", "pussy", "nazi", "hitler", "slut", "whore",
    "admin", "root", "moderator", "official", "agentwall", "quarantix",
)  # fmt: skip


def technique_tags(payload: str) -> list[str]:
    """Heuristic technique tags for an attack payload, sorted. "direct" when nothing else fits."""
    tags: set[str] = set()
    if _BASE64_RUN.search(payload) or _HEX_RUN.search(payload):
        tags.add("encoded")
    letters = [c for c in payload if c.isalpha()]
    if letters:
        non_latin = sum(1 for c in letters if not _is_latin(c))
        if non_latin / len(letters) > 0.5:
            tags.add("other_language")
    if _FAKE_SYSTEM.search(payload):
        tags.add("fake_system")
    if _URL.search(payload):
        tags.add("url")
    if _AUTHORITY.search(payload):
        tags.add("authority")
    if _SPLIT.search(payload):
        tags.add("split")
    if _ZERO_WIDTH.search(payload) or "<!--" in payload:
        tags.add("hidden")
    return sorted(tags) or ["direct"]


def _is_latin(char: str) -> bool:
    try:
        return "LATIN" in unicodedata.name(char)
    except ValueError:
        return False


def clean_nickname(name: str | None, rng: random.Random | None = None) -> str:
    """A safe display name. Anything blocked or empty becomes "Hacker-####"."""
    text = unicodedata.normalize("NFKC", name or "")
    text = _NICK_ALLOWED.sub("", text).strip()[:MAX_NICKNAME].strip()
    squashed = re.sub(r"[\W_]+", "", text.lower().translate(_LEET))
    if not text or any(word in squashed for word in _BLOCKED):
        number = (rng or random).randint(1000, 9999)
        return f"Hacker-{number}"
    return text
