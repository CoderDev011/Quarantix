"""The terminal view (scripts/qx_watch.py): verdicts, reasons and readable data paths."""

import importlib.util
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "qx_watch.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("qx_watch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blocked_event(enforced: bool) -> dict:
    return {
        "kind": "tool.call",
        "time": "2026-11-14T19:21:21.000+00:00",
        "tool": "run_shell",
        "outcome": "blocked" if enforced else "executed",
        "args": {"command": {"preview": "some command", "label": {"integrity": "untrusted"}}},
        "decision": {
            "kind": "block",
            "rule": "core/C1-untrusted-critical-arg",
            "reason": "The command was written by read_logs record L-201 (untrusted).",
            "enforced": enforced,
            "provenance": {"nodes": [
                {"title": "run_shell"}, {"title": "g3.command"},
                {"title": "read_logs L-201"}, {"title": "g2.service"},
            ]},
        },
    }  # fmt: skip


def test_blocked_and_would_block_lines() -> None:
    watch = load()
    paint = watch.Paint(False)
    lines = watch.format_event(blocked_event(True), paint)
    assert "BLOCKED" in lines[0] and "command=some command (untrusted)" in lines[0]
    assert any("core/C1-untrusted-critical-arg" in line for line in lines)
    assert any("run_shell ← command ← read_logs L-201" in line for line in lines)
    monitor = watch.format_event(blocked_event(False), paint)
    assert "WOULD BLOCK" in monitor[0] and any("monitor mode" in line for line in monitor)


def test_allowed_calls_are_one_line_and_other_kinds_are_skipped() -> None:
    watch = load()
    paint = watch.Paint(False)
    allowed = {"kind": "tool.call", "time": "2026-11-14T19:21:19", "tool": "list_alerts",
               "outcome": "executed", "args": {}, "decision": {"kind": "allow", "rule": "default"}}  # fmt: skip
    assert len(watch.format_event(allowed, paint)) == 1
    assert watch.format_event({"kind": "run.started"}, paint) == []


def test_runs_are_grouped_and_summarized() -> None:
    watch = load()
    runs = watch.group_runs(
        [{**blocked_event(True), "run_id": "a"}, {**blocked_event(False), "run_id": "b"}]
    )
    assert watch.summary(runs["a"]) == "1 calls, 1 blocked, 0 would-block, enforce"
    assert watch.summary(runs["b"]) == "1 calls, 0 blocked, 1 would-block, monitor"
