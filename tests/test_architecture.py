"""Architecture rules from AGENTS.md section 5. These run on every push."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GENERIC_PACKAGES = ("core", "ai", "engine", "guard", "sdk", "autopilot", "packs")
DOMAIN_WORDS = frozenset(
    {
        "ticket", "tickets", "refund", "refunds", "customer", "customers",
        "invoice", "invoices", "repo", "repos", "deploy", "deploys", "salary", "payroll",
    }
)  # fmt: skip
CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
LETTER_RUN = re.compile(r"[A-Za-z]+")


def domain_word_hits(line: str) -> list[str]:
    """Return the banned domain words found in one line of source.

    Identifiers are split on underscores and camelCase boundaries first, so
    `issue_refund`, `issueRefund` and `TICKET_STORE` are all caught, while
    different words such as `refunded` or `deployment` are not.
    """
    words = [w.lower() for w in LETTER_RUN.findall(CAMEL_BOUNDARY.sub(" ", line))]
    hits = []
    for index, word in enumerate(words):
        if word in DOMAIN_WORDS:
            hits.append(word)
        elif word == "order" and index + 1 < len(words) and words[index + 1] == "id":
            hits.append("order_id")
    return hits


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("def issue_refund(amount):", ["refund"]),
        ("issueRefund = make_tool()", ["refund"]),
        ("TICKET_STORE = {}", ["ticket"]),
        ("order_id = row[0]", ["order_id"]),
        ("orderId = row[0]", ["order_id"]),
        ("# list the repos", ["repos"]),
    ],
)
def test_scanner_finds_domain_words_inside_identifiers(line: str, expected: list[str]) -> None:
    assert domain_word_hits(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "# iterations run in order of completion",
        "deployment_id = 'x'",  # 'deployment' is a different word
        "refunded = False",  # past tense is a different word
        "repository_root = Path()",
    ],
)
def test_scanner_ignores_ordinary_words(line: str) -> None:
    assert domain_word_hits(line) == []


def test_generic_packages_never_name_a_domain() -> None:
    hits = []
    for package in GENERIC_PACKAGES:
        for path in sorted((ROOT / "quarantix" / package).rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if domain_word_hits(line):
                    hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert hits == [], "Domain words found in generic packages:\n" + "\n".join(hits)


def test_import_layering_contracts_hold() -> None:
    lint_imports = shutil.which("lint-imports") or str(Path(sys.executable).parent / "lint-imports")
    result = subprocess.run(
        [lint_imports, "--config", str(ROOT / "pyproject.toml")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
