"""Quarantix SDK (F12): local enforcement, policy sync and fail-safe for agents we did not write.

    qx = Quarantix(api_key=..., agent="support-agent", url="http://localhost:8000", registry=reg)
    async with qx:                                   # starts sync + event shipping
        pay, post = qx.wrap([pay, post])             # identical signatures
        async with qx.session(user_message):         # one guard session per conversation
            await agent.run(user_message)            # every wrapped call is checked locally

Decisions are made in-process (F04/F05/F11), so the agent keeps working when the
control plane is down. The network is handled by background tasks in the same
event loop: the bundle long-poll (which is also the heartbeat) and batched,
gzip-compressed event uploads. Nothing on the tool-call path waits for the network,
except an approval (a person must answer).

Fail-safe:
    online, fresh bundle            normal
    offline, verified cached bundle decide locally; ask becomes block; events buffer
    offline, no bundle ever         core rules only, and every high-risk sink is blocked
    bundle older than 24 h          high-risk sinks blocked
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import gzip
import inspect
import json
import os
import random
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import yaml

from quarantix.core.contracts import Decision, Event, ToolCallRequest
from quarantix.core.registry import Registry
from quarantix.engine.approvals import ApprovalResult
from quarantix.engine.gate import Gate, GateRuntime
from quarantix.engine.policy import Pack, PolicyBundle, compile_pack
from quarantix.guard.session import GuardSession

SDK_VERSION = "quarantix-sdk/0.1"
MAX_BUFFER = 10_000
FLUSH_EVERY_S = 0.25
FLUSH_AT = 100
MAX_BACKOFF_S = 10.0
STALE_AFTER_S = 24 * 3600
ONLINE_WINDOW_S = 35.0
POLL_WAIT_S = 25.0
APPROVAL_WAIT_S = 120.0


class HttpEventSink:
    """A bounded buffer (oldest dropped and counted) shipped by a background task."""

    def __init__(self, max_buffer: int = MAX_BUFFER) -> None:
        self.buffer: deque[Event] = deque()
        self.max_buffer = max_buffer
        self.dropped = 0
        self.sent = 0
        self._lock = threading.Lock()
        self._wake: asyncio.Event | None = None

    def emit(self, event: Event) -> None:
        with self._lock:
            if len(self.buffer) >= self.max_buffer:
                self.buffer.popleft()
                self.dropped += 1
            self.buffer.append(event)
            size = len(self.buffer)
        if size >= FLUSH_AT and self._wake is not None:
            self._wake.set()

    def take(self, limit: int = 500) -> list[Event]:
        with self._lock:
            items = [self.buffer.popleft() for _ in range(min(limit, len(self.buffer)))]
        return items

    def give_back(self, items: Sequence[Event]) -> None:
        """A failed upload: put the batch back in front (dropping the oldest if full)."""
        with self._lock:
            for event in reversed(items):
                if len(self.buffer) >= self.max_buffer:
                    self.dropped += 1
                    continue
                self.buffer.appendleft(event)


class HttpApprovalBroker:
    """F05's broker interface over the control plane: create, then long-poll the status."""

    def __init__(self, sdk: Quarantix) -> None:
        self.sdk = sdk

    async def open(self, request: ToolCallRequest, decision: Decision) -> str:
        response = await self.sdk._http().post(
            "/v1/approvals", json={"request": request.to_wire(), "decision": decision.to_wire()}
        )
        response.raise_for_status()
        return str(response.json()["id"])

    async def wait(self, approval_id: str, max_wait: float) -> ApprovalResult:
        deadline = time.monotonic() + min(max_wait, APPROVAL_WAIT_S)
        while (remaining := deadline - time.monotonic()) > 0:
            response = await self.sdk._http().get(
                f"/v1/approvals/{approval_id}/status",
                params={"wait": min(POLL_WAIT_S, remaining)},
                timeout=POLL_WAIT_S + 5,
            )
            response.raise_for_status()
            body = response.json()
            if body["status"] != "pending":
                return ApprovalResult(body["status"], body.get("scope", "once"))
        return ApprovalResult("expired")


class Quarantix:
    def __init__(
        self,
        *,
        api_key: str,
        agent: str,
        url: str = "http://localhost:8000",
        registry: Registry | None = None,
        cache_dir: str | Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        shadow: bool = False,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        if not api_key:
            raise ValueError("an API key is required")
        self.agent = agent
        self.url = url.rstrip("/")
        self.registry = registry or Registry()
        self.shadow = shadow
        self.cache = Path(cache_dir or Path.home() / ".quarantix" / agent) / "bundle.json"
        self._api_key = api_key  # never logged
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._clock = clock
        self._wall = wall
        self.events = HttpEventSink()
        self.approvals = HttpApprovalBroker(self)
        self.bundle: PolicyBundle | None = None
        self.bundle_fetched_wall: float | None = None
        self._loaded_at: float | None = None  # monotonic, when the bundle was taken into use
        self._age_at_load = 0.0
        self.last_sync: float | None = None  # monotonic time of the last successful poll
        self.warnings: list[str] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._session: contextvars.ContextVar[GuardSession | None] = contextvars.ContextVar(
            f"qx-session-{agent}", default=None
        )
        self.runtime = GateRuntime(
            Gate(self.registry, self._effective_bundle), self.approvals, self.events,
            offline=lambda: not self.online,
        )  # fmt: skip
        self._failsafe = _failsafe_pack(self.registry, agent)
        self._load_cache()

    # ---------------------------------------------------------------- status and policy

    @property
    def online(self) -> bool:
        return self.last_sync is not None and self._clock() - self.last_sync < ONLINE_WINDOW_S

    @property
    def bundle_age_s(self) -> float | None:
        if self._loaded_at is None:
            return None
        return self._age_at_load + (self._clock() - self._loaded_at)

    def status(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "online": self.online,
            "version": self.bundle.version if self.bundle else None,
            "last_sync_age_s": None
            if self.last_sync is None
            else round(self._clock() - self.last_sync, 1),
            "bundle_age_s": None if self.bundle_age_s is None else round(self.bundle_age_s, 1),
            "buffered_events": len(self.events.buffer),
            "dropped_events": self.events.dropped,
            "warnings": list(self.warnings[-5:]),
        }

    def _effective_bundle(self) -> PolicyBundle:
        if self.bundle is None:  # never had a policy: core rules + every high-risk sink blocked
            return PolicyBundle((self._failsafe,))
        age = self.bundle_age_s or 0.0
        if age > STALE_AFTER_S:
            return PolicyBundle((*self.bundle.packs, self._failsafe))
        return self.bundle

    def _use(self, bundle: PolicyBundle, fetched_wall: float) -> None:
        self.bundle = bundle
        self.bundle_fetched_wall = fetched_wall
        self._loaded_at = self._clock()
        self._age_at_load = max(0.0, self._wall() - fetched_wall)

    # ---------------------------------------------------------------- cache

    def _load_cache(self) -> None:
        try:
            data = json.loads(self.cache.read_text(encoding="utf-8"))
            bundle = _verify(data)
            self._use(bundle, float(data["fetched_at"]))
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError):
            self.warnings.append("the cached bundle is corrupted and was ignored")

    def _save_cache(self, wire: dict[str, Any], fetched_wall: float) -> None:
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
        tmp.write_text(json.dumps({**wire, "fetched_at": fetched_wall}), encoding="utf-8")
        os.replace(tmp, self.cache)  # atomic: a crash never leaves half a bundle

    # ---------------------------------------------------------------- lifecycle

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.url,
                transport=self._transport,
                timeout=httpx.Timeout(10.0, read=POLL_WAIT_S + 10),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-Quarantix-SDK": SDK_VERSION,
                },
            )
        return self._client

    async def start(self) -> None:
        if self._tasks:
            return
        self.events._wake = asyncio.Event()
        self._tasks = [
            asyncio.create_task(self._sync_loop()),
            asyncio.create_task(self._ship_loop()),
        ]

    async def stop(self, *, flush_timeout: float = 3.0) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        with contextlib.suppress(Exception):
            async with asyncio.timeout(flush_timeout):
                while self.events.buffer and await self._flush_once():
                    pass
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Quarantix:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def sync_now(self, wait: float = 0.0) -> bool:
        """One bundle poll (used at start and by tests). True when the poll succeeded."""
        headers = {"If-None-Match": f'"{self.bundle.version}"'} if self.bundle else {}
        response = await self._http().get(
            "/v1/policies/bundle", params={"agent": self.agent, "wait": wait}, headers=headers
        )
        if response.status_code == 304:
            self.last_sync = self._clock()
            return True
        response.raise_for_status()
        wire = response.json()
        bundle = _verify(wire)  # a bundle whose content does not match its version is refused
        fetched = self._wall()
        await asyncio.to_thread(self._save_cache, wire, fetched)
        self._use(bundle, fetched)
        self.last_sync = self._clock()
        return True

    async def _sync_loop(self) -> None:
        backoff = 0.5
        while True:
            try:
                await self.sync_now(wait=POLL_WAIT_S if self.bundle else 0.0)
                backoff = 0.5
                if self.events.buffer and self.events._wake is not None:
                    self.events._wake.set()  # back online: ship the buffer now, not after backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # offline or a bad bundle: keep the last verified one
                if isinstance(exc, ValueError):
                    self.warnings.append(f"refused a bundle: {exc}")
                await asyncio.sleep(backoff * (0.5 + random.random()))  # noqa: S311 (jitter)
                backoff = min(MAX_BACKOFF_S, backoff * 2)

    async def _flush_once(self) -> bool:
        batch = self.events.take()
        if not batch:
            return False
        body = gzip.compress(json.dumps({"events": [e.to_wire() for e in batch]}).encode())
        try:
            response = await self._http().post(
                "/v1/events:batch", content=body,
                headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            )  # fmt: skip
            response.raise_for_status()
        except Exception:
            self.events.give_back(batch)
            raise
        self.events.sent += len(batch)
        return True

    async def _ship_loop(self) -> None:
        backoff = FLUSH_EVERY_S
        wake = self.events._wake
        assert wake is not None
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), backoff)
            wake.clear()
            try:
                while await self._flush_once():
                    pass
                backoff = FLUSH_EVERY_S
            except asyncio.CancelledError:
                raise
            except Exception:
                backoff = min(2.0, max(FLUSH_EVERY_S, backoff * 2))

    # ---------------------------------------------------------------- sessions and wrapping

    def new_session(
        self, user_message: str | None = None, *, run_id: str | None = None
    ) -> GuardSession:
        session = GuardSession(
            self.registry, self.runtime, agent=self.agent,
            run_id=run_id or uuid.uuid4().hex[:12], shadow=self.shadow,
        )  # fmt: skip
        if user_message:
            session.observe_user(user_message)
        return session

    @contextlib.asynccontextmanager
    async def session(
        self, user_message: str | None = None, *, run_id: str | None = None
    ) -> AsyncIterator[GuardSession]:
        """One guard session for this task (context-local: concurrent tasks never mix)."""
        session = self.new_session(user_message, run_id=run_id)
        token = self._session.set(session)
        try:
            yield session
        finally:
            self._session.reset(token)

    @contextlib.contextmanager
    def session_sync(self, user_message: str | None = None) -> Iterator[GuardSession]:
        session = self.new_session(user_message)
        token = self._session.set(session)
        try:
            yield session
        finally:
            self._session.reset(token)

    def current(self) -> GuardSession:
        session = self._session.get()
        if session is None:  # a call outside any session gets its own (nothing is unguarded)
            session = self.new_session()
            self._session.set(session)
        return session

    def wrap(self, functions: Sequence[Callable[..., Any]]) -> list[Callable[..., Any]]:
        """Wrap tool functions. Each wrapper has the original's name and signature."""
        return [self._wrap_one(fn) for fn in functions]

    def _wrap_one(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        name = getattr(fn, "__name__", "tool")
        signature = inspect.signature(fn)

        def bind(*args: Any, **kwargs: Any) -> dict[str, Any]:
            """Named arguments as the Gate sees them (a `**kwargs` parameter is flattened)."""
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments: dict[str, Any] = {}
            for key, value in bound.arguments.items():
                if signature.parameters[key].kind is inspect.Parameter.VAR_KEYWORD:
                    arguments.update(value)
                elif signature.parameters[key].kind is inspect.Parameter.VAR_POSITIONAL:
                    raise TypeError(f"{name}: tools with *args cannot be guarded")
                else:
                    arguments[key] = value
            return arguments

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def guarded_async(*args: Any, **kwargs: Any) -> Any:
                arguments = bind(*args, **kwargs)

                async def invoke() -> Any:
                    return await fn(**arguments)

                return await self.current().call(name, arguments, invoke)

            guarded_async.__signature__ = signature  # type: ignore[attr-defined]
            return guarded_async

        @functools.wraps(fn)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            arguments = bind(*args, **kwargs)
            session = self.current()
            coroutine = session.call(name, arguments, lambda: fn(**arguments))
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(coroutine)  # a plain sync agent with no loop of its own
            coroutine.close()
            raise RuntimeError(
                f"{name} is sync but was called inside an event loop; wrap an async tool"
            )

        guarded.__signature__ = signature  # type: ignore[attr-defined]
        return guarded


def _verify(wire: Any) -> PolicyBundle:
    """Recompile the packs and check the content hash against the advertised version."""
    if not isinstance(wire, dict) or not isinstance(wire.get("packs"), list):
        raise ValueError("not a bundle")
    packs = [compile_pack(str(item["yaml"])) for item in wire["packs"]]
    bundle = PolicyBundle(packs)
    if bundle.version != wire.get("version"):
        raise ValueError("the bundle content does not match its version")
    return bundle


def _failsafe_pack(registry: Registry, agent: str) -> Pack:
    """Blocks every high-risk sink (used with no policy at all, or a policy older than 24 h)."""
    rules: list[dict[str, Any]] = []
    for name in registry.names():
        spec = registry.get(name)
        if spec.kind != "source" and spec.risk == "high":
            rules.append({
                "name": f"failsafe-{name}"[:60], "tool": name, "decision": "block",
                "reason": "No fresh policy is available, so high-risk actions are blocked.",
            })  # fmt: skip
    if not registry.names():  # nothing known: every action is high-risk by default
        rules.append({"name": "failsafe-all", "tool": "*", "decision": "block",
                      "reason": "No policy is available, so actions are blocked."})  # fmt: skip
    text = yaml.safe_dump(
        {"schema_version": 1, "pack": "_failsafe", "applies_to": [agent], "rules": rules}
    )
    return compile_pack(text)
