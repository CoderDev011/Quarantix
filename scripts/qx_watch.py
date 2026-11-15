"""AgentWall in the terminal: every decision, with its reason and data path.

    uv run python scripts/qx_watch.py                       # live: new decisions as they happen
    uv run python scripts/qx_watch.py --runs                # list recorded runs (newest last)
    uv run python scripts/qx_watch.py --replay d5626bc8     # replay a recorded run (no model)
    uv run python scripts/qx_watch.py --replay last --speed 1.5

Reads AGENTWALL_ADMIN_TOKEN from the environment or `.env` (never printed) and talks to
QX_API (default http://127.0.0.1:8000). Filter with --agent (default devops-agent;
"all" for every agent).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
COLORS = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "dim": "2",
    "bold": "1",
    "cyan": "36",
}
PREVIEW = 70


class Paint:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles:
            return text
        codes = ";".join(COLORS[s] for s in styles)
        return f"\033[{codes}m{text}\033[0m"


def verdict(wire: Mapping[str, Any]) -> tuple[str, str]:
    """(label, color) for one tool.call event."""
    decision = wire.get("decision") or {}
    if wire.get("outcome") == "blocked":
        return "BLOCKED", "red"
    if decision and not decision.get("enforced", True) and decision.get("kind") != "allow":
        return ("WOULD BLOCK" if decision.get("kind") == "block" else "WOULD ASK"), "yellow"
    if wire.get("outcome") == "error":
        return "ERROR", "dim"
    if decision.get("kind") == "ask":
        return "APPROVED", "blue"
    return "ALLOWED", "green"


def _args(wire: Mapping[str, Any]) -> str:
    parts = []
    for name, preview in (wire.get("args") or {}).items():
        shown = str((preview or {}).get("preview", ""))
        if len(shown) > PREVIEW:
            shown = shown[: PREVIEW - 1] + "…"
        integrity = ((preview or {}).get("label") or {}).get("integrity", "")
        mark = " (untrusted)" if integrity == "untrusted" else ""
        parts.append(f"{name}={shown}{mark}")
    return ", ".join(parts)


def readable_path(titles: list[str]) -> str:
    """'run_shell ← command ← read_logs L-201': action, argument, the record it came from."""
    out: list[str] = []
    for title in titles:
        if not title:
            continue
        name = title.split(".", 1)[1] if re.fullmatch(r"[gs]\d+(\[\d+\])?\.\w+", title) else title
        if name not in out:
            out.append(name)
        if " " in title:  # a record node ("read_logs L-201"): where the value came from
            break
    return " ← ".join(out)


def format_event(wire: Mapping[str, Any], paint: Paint) -> list[str]:
    """The lines shown for one event (only tool calls and approvals are shown)."""
    kind = wire.get("kind")
    clock = str(wire.get("time", ""))[11:19]
    if kind == "approval.requested":
        data = wire.get("data") or {}
        return [paint(f"  {clock}  ✋ asking a person: {data.get('reason', '')}", "blue")]
    if kind != "tool.call":
        return []
    label, color = verdict(wire)
    decision = wire.get("decision") or {}
    head = (
        f"  {paint(clock, 'dim')}  {paint(f'{label:<11}', color, 'bold')} "
        f"{paint(str(wire.get('tool')), 'bold')}({_args(wire)})"
    )
    lines = [head]
    rule = decision.get("rule")
    if label in ("BLOCKED", "WOULD BLOCK", "WOULD ASK") or (rule and rule != "default"):
        lines.append(f"               {paint('rule', 'dim')}   {rule}")
    if label in ("BLOCKED", "WOULD BLOCK", "WOULD ASK"):
        lines.append(f"               {paint('why', 'dim')}    {decision.get('reason', '')}")
        nodes = (decision.get("provenance") or {}).get("nodes", [])
        path = readable_path([str(n.get("title", "")) for n in nodes])
        if path:
            lines.append(f"               {paint('path', 'dim')}   {paint(path, 'cyan')}")
        if label == "WOULD BLOCK":
            lines.append(paint("               (monitor mode: logged, not stopped)", "yellow"))
    return lines


def _token() -> str:
    token = os.environ.get("AGENTWALL_ADMIN_TOKEN", "")
    env = ROOT / ".env"
    if not token and env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("AGENTWALL_ADMIN_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        sys.exit("set AGENTWALL_ADMIN_TOKEN (or put it in .env)")
    return token


def _history(client: httpx.Client, agent: str | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"limit": 500, "kind": ["tool.call", "approval.requested"]}
    if agent:
        params["agent"] = agent
    events: list[dict[str, Any]] = []
    since = 0
    while True:
        page = (
            client.get("/v1/events", params={**params, "since": since})
            .raise_for_status()
            .json()["events"]
        )
        events.extend(page)
        if len(page) < 500:
            return events
        since = page[-1]["seq"]


def group_runs(events: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    runs: dict[str, list[Mapping[str, Any]]] = {}
    for wire in events:
        runs.setdefault(str(wire.get("run_id")), []).append(wire)
    return runs


def summary(run: list[Mapping[str, Any]]) -> str:
    calls = [w for w in run if w.get("kind") == "tool.call"]
    blocked = sum(1 for w in calls if w.get("outcome") == "blocked")
    would = sum(1 for w in calls if verdict(w)[0].startswith("WOULD"))
    enforced = any((w.get("decision") or {}).get("enforced") for w in calls)
    mode = "enforce" if enforced else "monitor"
    return f"{len(calls)} calls, {blocked} blocked, {would} would-block, {mode}"


def _sse(response: httpx.Response) -> Iterator[dict[str, Any]]:
    data: list[str] = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line and data:
            with contextlib.suppress(ValueError):
                yield json.loads("\n".join(data))
            data = []


def live(client: httpx.Client, agent: str | None, paint: Paint) -> None:
    newest = max((w["seq"] for w in _history(client, agent)), default=0)
    print(paint(f"Watching {agent or 'all agents'} live (Ctrl+C to stop)…", "dim"))
    current_run = None
    while True:
        params: dict[str, Any] = {"since": newest, "kind": ["tool.call", "approval.requested"]}
        if agent:
            params["agent"] = agent
        try:
            with client.stream("GET", "/v1/events/stream", params=params, timeout=None) as response:
                response.raise_for_status()
                for wire in _sse(response):
                    if "seq" not in wire:
                        continue
                    newest = max(newest, wire["seq"])
                    if wire.get("run_id") != current_run:
                        current_run = wire.get("run_id")
                        print(
                            paint(
                                f"\n── run {str(current_run)[:12]} · {wire.get('agent')} ──", "bold"
                            )
                        )
                    for line in format_event(wire, paint):
                        print(line, flush=True)
        except httpx.HTTPError:
            print(paint("  (connection lost; reconnecting…)", "dim"), flush=True)
            time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--agent", default="devops-agent")
    parser.add_argument("--runs", action="store_true", help="list recorded runs")
    parser.add_argument("--replay", metavar="RUN", help="a run id prefix, or 'last'")
    parser.add_argument("--speed", type=float, default=1.0, help="seconds between replayed calls")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()
    agent = None if args.agent == "all" else args.agent
    paint = Paint(not args.no_color and sys.stdout.isatty())
    url = os.environ.get("QX_API", "http://127.0.0.1:8000")
    with httpx.Client(
        base_url=url, headers={"Authorization": f"Bearer {_token()}"}, timeout=30
    ) as client:
        try:
            if args.runs or args.replay:
                runs = group_runs(_history(client, agent))
                if args.runs:
                    for run_id, run in runs.items():
                        when = str(run[0].get("time", ""))[:19]
                        print(f"  {run_id[:12]}  {when}  {run[0].get('agent')}  {summary(run)}")
                    return 0
                chosen = (
                    list(runs)[-1:]
                    if args.replay == "last"
                    else [r for r in runs if r.startswith(args.replay)]
                )
                if not chosen:
                    sys.exit(f"no run starting with {args.replay!r}; list them with --runs")
                run = runs[chosen[0]]
                when = str(run[0].get("time", ""))[:19]
                agent_name = run[0].get("agent")
                print(
                    paint(
                        f"── replay of run {chosen[0][:12]} · {agent_name} · {when} UTC ──", "bold"
                    )
                )
                for wire in run:
                    for line in format_event(wire, paint):
                        print(line, flush=True)
                    time.sleep(max(0.0, args.speed))
                print(paint(f"── {summary(run)} ──", "bold"))
                return 0
            live(client, agent, paint)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            sys.exit(f"the control plane answered {status}: check QX_API and the admin token")
        except httpx.ConnectError:
            sys.exit(f"cannot reach {url}: is the stack running? (bash scripts/demo_prep.sh)")
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
