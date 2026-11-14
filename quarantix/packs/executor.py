"""Generic tool executor (F03, contracts 10.3): one implementation per behavior.

`bind_registry(world)` returns a registry whose tools run against that world.
The decision metadata is the domain's (identical registry version); only the
implementation is bound. Implementations are async and purely in-memory, except
that attacker addresses are delivered through the world's attacker link. Nothing
is ever executed: `run_command` is a fake shell that only records.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from quarantix.core.registry import Registry
from quarantix.packs.model import ToolManifest

if TYPE_CHECKING:
    from quarantix.packs.world import World

_URL = re.compile(r"https?://[^\s<>\"'`|;]+", re.IGNORECASE)
_EMPTY_FILTERS = frozenset({"", "*", "all", "any"})
MAX_LIST = 500

Impl = Callable[..., Awaitable[Any]]


class ToolError(Exception):
    """A tool refused the call (unknown record, ownership check, bad arguments)."""


def bind_registry(world: World) -> Registry:
    registry = Registry()
    for manifest in world.domain.tools.values():
        registry.register(replace(manifest.spec, fn=_implementation(manifest, world)))
    return registry


def _implementation(manifest: ToolManifest, world: World) -> Impl:
    run = _BEHAVIORS[manifest.behavior]
    params = frozenset(manifest.params)
    name = manifest.spec.name

    async def tool(**kwargs: Any) -> Any:
        unknown = sorted(set(kwargs) - params)
        if unknown:
            raise ToolError(f"{name}: unknown argument(s) {unknown}")
        missing = sorted(manifest.required - set(kwargs))
        if missing:
            raise ToolError(f"{name}: missing argument(s) {missing}")
        return await run(manifest, world, kwargs)

    tool.__name__ = name
    tool.__doc__ = manifest.spec.description
    return tool


# ---------------------------------------------------------------- sources


async def _list_records(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    cfg = m.config
    rows = world.records(cfg["store"])
    for param, field in cfg.get("filters", {}).items():
        wanted = args.get(param)
        if wanted is None or (isinstance(wanted, str) and wanted.strip().lower() in _EMPTY_FILTERS):
            continue
        rows = [row for row in rows if _same(row.get(field), wanted)]
    limit = MAX_LIST
    limit_param = cfg.get("limit_param")
    if limit_param and args.get(limit_param) is not None:
        try:
            limit = max(1, min(MAX_LIST, int(args[limit_param])))
        except (TypeError, ValueError):
            raise ToolError(f"{m.spec.name}: {limit_param} must be a whole number") from None
    rows = rows[-limit:]  # the most recent records
    if cfg.get("newest_first"):
        rows.reverse()
    return rows


async def _get_record(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    cfg = m.config
    record_id = str(args.get(cfg["id_param"], ""))
    record = world.get(cfg["store"], record_id)
    if record is None:
        raise ToolError(f"no record {record_id!r} in {cfg['store']}")
    owner_field = cfg.get("owner_field")
    if owner_field is not None:
        owner = args.get(cfg["owner_param"])
        if not _same(record.get(owner_field), owner):
            raise ToolError("record not owned by this owner")
    return record


async def _read_secret(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    cfg = m.config
    name = str(args.get(cfg["name_param"], ""))
    record = world.get(cfg["store"], name)
    if record is None:
        raise ToolError(f"no secret named {name!r}")
    return record.get(cfg.get("value_field", "value"))


async def _fetch_page(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    cfg = m.config
    url = str(args.get(cfg.get("url_param", "url"), "")).strip()
    page = world.get(cfg["store"], url)
    return "404 page" if page is None else page.get(cfg.get("content_field", "text"), "")


# ---------------------------------------------------------------- sinks


async def _ledger_write(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    world.append(m.config["ledger"], args)
    return "ok"


async def _post_internal(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    cfg = m.config
    channel = str(args.get(cfg["channel_param"], ""))
    text = _text(args.get(cfg.get("text_param", "text"), ""))
    world.append(cfg["ledger"], args)
    if channel.lower().startswith(("http://", "https://")):
        await world.link.send("POST", channel, text)  # a webhook "channel": only the attacker
    return "posted"


async def _send_external(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    cfg = m.config
    destination = str(args.get(cfg["destination_param"], "")).strip()
    body = _text({k: v for k, v in args.items() if k != cfg["destination_param"]})
    world.append(cfg["ledger"], args)
    if "://" in destination:
        await world.link.send("POST", destination, body)
    else:
        await world.link.mail(destination, body)
    return "sent"


async def _run_command(m: ToolManifest, world: World, args: Mapping[str, Any]) -> Any:
    command = str(args.get(m.config.get("command_param", "command"), ""))
    world.append(m.config["ledger"], args)
    sends_data = any(flag in command.split() for flag in ("-d", "--data", "-F", "-T", "--data-raw"))
    for match in _URL.finditer(command):  # what the attacker would receive: the URL and any data
        if await world.link.send(
            "POST" if sends_data else "GET", match.group(0).rstrip(".,)"), command
        ):
            break  # one request to the attacker host at most
    return "command finished (exit 0)"


_BEHAVIORS: Mapping[str, Callable[[ToolManifest, World, Mapping[str, Any]], Awaitable[Any]]] = {
    "list_records": _list_records,
    "get_record": _get_record,
    "read_secret": _read_secret,
    "fetch_page": _fetch_page,
    "ledger_write": _ledger_write,
    "post_internal": _post_internal,
    "send_external": _send_external,
    "run_command": _run_command,
}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    return str(a).strip().casefold() == str(b).strip().casefold()


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)
