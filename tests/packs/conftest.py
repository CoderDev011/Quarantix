from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from quarantix.packs.loader import load_domain
from quarantix.packs.model import Domain

DOMAINS = Path(__file__).resolve().parents[2] / "domains"


@pytest.fixture(scope="session")
def support() -> Domain:
    return load_domain(DOMAINS / "support")


@pytest.fixture(scope="session")
def devops() -> Domain:
    return load_domain(DOMAINS / "devops")


@pytest.fixture
def edit_pack(tmp_path: Path) -> Callable[..., Path]:
    """Copy a pack to a temp folder and apply text replacements to one of its files."""

    def make(name: str, edits: dict[str, str], file: str = "domain.yaml") -> Path:
        target = tmp_path / name
        shutil.copytree(DOMAINS / name, target)
        path = target / file
        text = path.read_text(encoding="utf-8")
        for old, new in edits.items():
            assert old in text, f"edit target not found: {old!r}"
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")
        return target

    return make
