"""The Docker image ships every file the running product reads (found missing on 2026-11-15)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_image_copies_everything_the_api_reads_at_runtime() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    for needed in ("domains/", "redteam/", "proof/", "docs/incidents.md", "cassettes/"):
        assert f"COPY {needed}" in dockerfile, f"the image does not copy {needed}"
    assert "!docs/incidents.md" in ignored, "docs/ is ignored, so incidents.md must be re-included"
