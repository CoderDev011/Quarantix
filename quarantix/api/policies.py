"""Policy service (F13): the live bundle, its version, and change notification.

Packs are compiled before they are saved, so a stored pack always compiles.
Agent modes live in a generated `_modes` pack, so a mode change is an ordinary
bundle change: the version bumps and every long-polling agent wakes up.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Mapping
from typing import Any

import yaml

from quarantix.api.store import Store
from quarantix.engine.policy import AGENT_MODES, Pack, PolicyBundle, compile_pack

MODES_PACK = "_modes"
AGENT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class PolicyService:
    def __init__(self, store: Store) -> None:
        self.store = store
        self._texts: dict[str, str] = {}
        self._packs: dict[str, Pack] = {}
        self._modes: dict[str, str] = {}
        self.bundle = PolicyBundle(())
        self._changed = asyncio.Condition()

    async def load(self) -> None:
        for name, text in (await self.store.load_packs()).items():
            pack = compile_pack(text)  # stored packs were compiled before saving
            self._texts[name], self._packs[name] = text, pack
            if name == MODES_PACK:
                self._modes = dict(pack.modes)
        self._rebuild()

    @property
    def version(self) -> str:
        return self.bundle.version

    def texts(self) -> Mapping[str, str]:
        return dict(self._texts)

    def mode(self, agent: str) -> str:
        return self.bundle.for_agent(agent).mode

    async def put_pack(self, name: str, text: str) -> str:
        """Compile, then save. Raises PolicyError (with a line) or ValueError."""
        if name == MODES_PACK:
            raise ValueError(f"{MODES_PACK!r} is managed through agent modes")
        pack = compile_pack(text)
        if pack.name != name:
            raise ValueError(f"the pack is named {pack.name!r}, but the path says {name!r}")
        await self.store.save_pack(name, text, pack.origin)
        self._texts[name], self._packs[name] = text, pack
        await self._changed_now()
        return self.version

    async def delete_pack(self, name: str) -> str:
        if name == MODES_PACK:
            raise ValueError(f"{MODES_PACK!r} is managed through agent modes")
        if name not in self._texts:
            raise KeyError(name)
        await self.store.delete_pack(name)
        del self._texts[name], self._packs[name]
        await self._changed_now()
        return self.version

    def origins(self) -> dict[str, str]:
        """Pack name -> origin (human, autopilot, day-one)."""
        return {name: pack.origin for name, pack in self._packs.items()}

    async def set_mode(self, agent: str, mode: str) -> str:
        if not AGENT_NAME.match(agent):
            raise ValueError(f"invalid agent name {agent!r}")
        if mode not in AGENT_MODES:
            raise ValueError(f"invalid mode {mode!r}; use {sorted(AGENT_MODES)}")
        modes = {**self._modes, agent: mode}
        document: dict[str, Any] = {
            "schema_version": 1,
            "pack": MODES_PACK,
            "modes": modes,
            "rules": [],
        }
        text = yaml.safe_dump(document, sort_keys=True)  # safe_dump: names can never inject YAML
        pack = compile_pack(text)
        await self.store.save_pack(MODES_PACK, text, "human")
        self._texts[MODES_PACK], self._packs[MODES_PACK], self._modes = text, pack, modes
        await self._changed_now()
        return self.version

    def wire_bundle(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "version": self.version,
            "packs": [{"name": name, "yaml": self._texts[name]} for name in sorted(self._texts)],
        }

    async def wait_for_change(self, known_version: str | None, max_wait: float) -> None:
        """Return as soon as the version differs from `known_version`, or after `max_wait`."""
        if known_version != self.version or max_wait <= 0:
            return
        async with self._changed:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._changed.wait_for(lambda: self.version != known_version), max_wait
                )

    def _rebuild(self) -> None:
        self.bundle = PolicyBundle(self._packs.values())

    async def _changed_now(self) -> None:
        self._rebuild()
        async with self._changed:
            self._changed.notify_all()
