"""Red-team runner CLI (F21). Prints a Markdown table; writes the JSON report.

Replay (free, deterministic, the default) re-issues recorded tool-call traces:
    uv run python scripts/redteam.py --modes baseline,guard,full

Live (costs model calls; check the balance first, docs/SPIKES.md), recording traces:
    LLM_MODE=live uv run python scripts/redteam.py --live --record-traces --modes baseline

Exit code 0 when the run completed (it does not judge the numbers).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from quarantix.api.runtime import build_models  # noqa: E402
from quarantix.arena.suite import (  # noqa: E402
    Trace,
    cases_for,
    load_traces,
    markdown,
    run_live,
    run_suite,
    save_traces,
)
from quarantix.engine.policy import PolicyBundle, compile_pack  # noqa: E402
from quarantix.packs.loader import load_all  # noqa: E402


def _commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=5,
        ).stdout.strip()  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--modes", default="baseline,guard,full")
    parser.add_argument("--domains", default="", help="comma-separated; default: every pack")
    parser.add_argument("--ask-policy", choices=["deny", "approve", "both"], default="both")
    parser.add_argument("--live", action="store_true", help="run the naive agent with a real model")
    parser.add_argument("--record-traces", action="store_true", help="save baseline traces (live)")
    parser.add_argument("--day-one", action="store_true", help="use each pack's day-one policy")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--out", default=str(ROOT / "redteam" / "results.json"))
    args = parser.parse_args()

    domains = load_all(ROOT / "domains")
    if args.domains:
        wanted = set(args.domains.split(","))
        domains = {n: d for n, d in domains.items() if n in wanted}
    modes = [m for m in args.modes.split(",") if m]

    def policy_for(domain):
        pack = compile_pack(domain.day_one_text) if args.day_one else domain.policy
        bundle = PolicyBundle((pack,))
        return lambda: bundle

    models = build_models()
    brains = models.brains()
    traces_dir = ROOT / "redteam" / "traces"
    try:
        if args.live and args.record_traces:
            for domain in domains.values():
                recorded: dict[str, Trace] = {}
                for case in cases_for(domain):
                    _, trace = await run_live(domain, case, "baseline", brains, policy_for(domain))
                    if trace is not None:
                        recorded[case.id] = trace
                save_traces(traces_dir / f"{domain.name}.json", recorded, source="recorded",
                            model=brains.naive_model)  # fmt: skip
                print(f"recorded {len(recorded)} traces for {domain.name}")
        traces = None if args.live else {n: load_traces(traces_dir / f"{n}.json") for n in domains}
        report = await run_suite(
            domains.values(),
            modes,
            policy_for,
            traces=traces,
            brains=brains if args.live else None,
            reader=brains.reader,
            ask_policy=args.ask_policy,
            concurrency=args.concurrency,
        )
    finally:
        await models.close()
    report.git_commit = _commit()
    sources = sorted({t.source for per in (traces or {}).values() for t in per.values()})
    print(markdown(report))
    if sources:
        note = "scripted traces are hand-written, not a model run"
        print(f"\ntrace sources: {', '.join(sources)} ({note})")
    out = Path(args.out)
    await asyncio.to_thread(_write, out, json.dumps(report.to_wire(), indent=2) + "\n")
    print(f"report: {out}")
    return 0


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
