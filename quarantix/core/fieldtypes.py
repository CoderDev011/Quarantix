"""Reader field types (docs/contracts.md section 4).

A field type says what the quarantined reader may return for one field. `coerce`
is the authority: our code re-checks every value the model returns (some models
ignore schema constraints) and turns anything out of bounds into None.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MONEY = re.compile(r"^money\(\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)\s*\)$")
SHORT_TEXT_LIMIT = 80
TEXT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class FieldType:
    spec: str
    json_schema: Mapping[str, Any]
    _check: Callable[[Any], Any] = field(compare=False, repr=False)

    def coerce(self, value: Any) -> Any:
        """The value if it fits this type, otherwise None. Never raises."""
        if value is None:
            return None
        try:
            return self._check(value)
        except (TypeError, ValueError):
            return None


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def parse_field_type(spec: str) -> FieldType:
    """Parse one field type spec. Raises ValueError for anything not in the contract."""
    spec = spec.strip()
    if spec == "bool":
        return FieldType(
            spec, _nullable({"type": "boolean"}), lambda v: v if isinstance(v, bool) else None
        )
    if spec == "int":
        return FieldType(
            spec,
            _nullable({"type": "integer"}),
            lambda v: v if isinstance(v, int) and not isinstance(v, bool) else None,
        )
    if spec == "number":
        return FieldType(
            spec, _nullable({"type": "number"}), lambda v: v if _is_number(v) else None
        )
    if spec == "email":
        return FieldType(
            spec,
            _nullable({"type": "string", "format": "email"}),
            lambda v: v if isinstance(v, str) and _EMAIL.match(v) else None,
        )
    if spec == "url":

        def url(value: Any) -> Any:
            if not isinstance(value, str):
                return None
            parts = urlsplit(value)
            return value if parts.scheme in ("http", "https") and parts.netloc else None

        return FieldType(spec, _nullable({"type": "string", "format": "uri"}), url)
    if spec == "short_text":
        return _text_type(spec, SHORT_TEXT_LIMIT)
    if spec.startswith("text:"):
        limit = spec[len("text:") :]
        if not limit.isdigit() or not 1 <= int(limit) <= TEXT_LIMIT:
            raise ValueError(f"text length must be 1..{TEXT_LIMIT}: {spec!r}")
        return _text_type(spec, int(limit))
    if spec.startswith("pattern:"):
        try:
            pattern = re.compile(spec[len("pattern:") :])
        except re.error as exc:
            raise ValueError(f"invalid pattern in {spec!r}: {exc}") from None
        return FieldType(
            spec,
            _nullable({"type": "string", "pattern": pattern.pattern}),
            lambda v: v if isinstance(v, str) and pattern.fullmatch(v) else None,
        )
    if spec.startswith("enum:"):
        options = spec[len("enum:") :].split("|")
        if not options or any(not option for option in options):
            raise ValueError(f"enum needs non-empty options: {spec!r}")
        allowed = frozenset(options)
        return FieldType(
            spec,
            _nullable({"type": "string", "enum": options}),
            lambda v: v if isinstance(v, str) and v in allowed else None,
        )
    match = _MONEY.match(spec)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        if low > high:
            raise ValueError(f"money minimum is above maximum: {spec!r}")
        return FieldType(
            spec,
            _nullable({"type": "number", "minimum": low, "maximum": high}),
            lambda v: float(v) if _is_number(v) and low <= v <= high else None,
        )
    raise ValueError(f"unknown field type {spec!r}")


def _text_type(spec: str, limit: int) -> FieldType:
    return FieldType(
        spec,
        _nullable({"type": "string", "maxLength": limit}),
        lambda v: v if isinstance(v, str) and len(v) <= limit else None,
    )
