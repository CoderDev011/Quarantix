"""Arena HTTP routes (F15). Public routes never return payload text.

No `from __future__ import annotations`: FastAPI resolves these type hints at import.
"""

import asyncio
import json
import secrets
import time
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from quarantix.api.schemas import (
    AdminAttemptsPage,
    ArenaStatsOut,
    AttemptOut,
    AutopilotProgressOut,
    GoalsPage,
    LeaderboardPage,
    ResetOut,
)
from quarantix.arena.service import ArenaError, ArenaService

PLAYER_COOKIE = "qx_player"
MAX_WAIT_S = 25.0


class AttemptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(max_length=64)
    goal_id: str = Field(max_length=64)
    payload: str = Field(max_length=4000)  # the 600-character rule is the arena's (413)
    nickname: str | None = Field(default=None, max_length=64)


class HideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: str | None = None
    player_id: str | None = None


class ResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clear_leaderboard: bool = False
    restore_policies: bool = True


def _arena(request: Request) -> ArenaService:
    arena = getattr(request.app.state, "arena", None)
    if arena is None:
        raise ArenaError(503, "arena_unavailable", "The arena is not configured on this server.")
    return arena


def _client_ip(request: Request) -> str:
    for header in ("cf-connecting-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def _error(exc: ArenaError) -> JSONResponse:
    return JSONResponse(
        {"error": exc.code, "message": exc.message, "details": {}}, status_code=exc.status
    )


def arena_router(require_admin: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/v1/arena")
    Admin = Depends(require_admin)

    @router.get("/goals", response_model=GoalsPage)
    async def goals(request: Request) -> dict[str, Any]:
        return {"goals": _arena(request).goals()}

    @router.post("/attempts", response_model=AttemptOut)
    async def submit(request: Request, body: AttemptIn) -> JSONResponse:
        player = request.cookies.get(PLAYER_COOKIE)
        if not player or len(player) > 64:
            player = secrets.token_urlsafe(16)
        try:
            attempt = await _arena(request).submit(
                player_id=player,
                nickname=body.nickname,
                ip=_client_ip(request),
                domain=body.domain,
                goal_id=body.goal_id,
                payload=body.payload,
            )
        except ArenaError as exc:
            return _error(exc)
        response = JSONResponse(attempt.to_public(), status_code=202)
        response.set_cookie(
            PLAYER_COOKIE, player, max_age=7 * 24 * 3600, httponly=True, samesite="lax",
            secure=request.url.scheme == "https", path="/",
        )  # fmt: skip
        return response

    @router.get("/attempts/{attempt_id}", response_model=AttemptOut)
    async def attempt(
        request: Request,
        attempt_id: str,
        wait: Annotated[float, Query(ge=0, le=60)] = 0.0,
    ) -> JSONResponse:
        arena = _arena(request)
        try:
            found = await arena.wait(attempt_id, min(wait, MAX_WAIT_S))
        except ArenaError as exc:
            return _error(exc)
        if found.hidden:
            return _error(ArenaError(404, "not_found", "no such attempt"))
        return JSONResponse(found.to_public())

    @router.get("/attempts/{attempt_id}/autopilot", response_model=AutopilotProgressOut)
    async def attempt_autopilot(request: Request, attempt_id: str) -> JSONResponse:
        progress = _arena(request).autopilot.get(attempt_id)
        if progress is None:
            return _error(ArenaError(404, "not_found", "no Autopilot activity for this attempt"))
        return JSONResponse(progress)

    @router.get("/leaderboard", response_model=LeaderboardPage)
    async def leaderboard(request: Request) -> dict[str, Any]:
        return {"leaderboard": _arena(request).leaderboard(20)}

    @router.get("/stats", response_model=ArenaStatsOut)
    async def stats(request: Request) -> dict[str, Any]:
        return _arena(request).stats()

    @router.get("/stream")
    async def stream(request: Request) -> EventSourceResponse:
        arena = _arena(request)
        queue = arena.subscribe()

        async def messages() -> AsyncIterator[dict[str, str]]:
            try:
                yield {
                    "event": "stats",
                    "data": json.dumps({"type": "stats", "stats": arena.stats()}),
                }
                while True:
                    message = await queue.get()
                    yield {
                        "event": str(message.get("type", "message")),
                        "data": json.dumps(message),
                    }
            except asyncio.CancelledError:
                raise
            finally:
                arena.unsubscribe(queue)

        return EventSourceResponse(messages(), ping=15)

    # ---------------------------------------------------------------- moderation (admin)

    @router.get("/admin/attempts", dependencies=[Admin], response_model=AdminAttemptsPage)
    async def admin_attempts(
        request: Request, limit: Annotated[int, Query(ge=1, le=500)] = 100
    ) -> dict[str, Any]:
        arena = _arena(request)
        items = list(arena.attempts.values())[-limit:]
        return {"attempts": [a.to_admin() for a in reversed(items)]}

    @router.post("/admin/hide", dependencies=[Admin])
    async def hide(request: Request, body: HideIn) -> JSONResponse:
        arena = _arena(request)
        try:
            if body.attempt_id:
                arena.hide_attempt(body.attempt_id)
            if body.player_id:
                arena.hide_player(body.player_id)
        except ArenaError as exc:
            return _error(exc)
        return JSONResponse({"ok": True})

    @router.post("/admin/pause", dependencies=[Admin])
    async def pause(request: Request) -> dict[str, Any]:
        _arena(request).pause()
        return {"paused": True}

    @router.post("/admin/resume", dependencies=[Admin])
    async def resume(request: Request) -> dict[str, Any]:
        _arena(request).resume()
        return {"paused": False}

    @router.post("/admin/reset", dependencies=[Admin], response_model=ResetOut)
    async def reset(request: Request, body: ResetIn) -> dict[str, Any]:
        """Booth reset: day-one policies back, Autopilot rules off, cached results gone."""
        start = time.perf_counter()
        arena = _arena(request)
        restored: list[str] = []
        removed: list[str] = []
        if body.restore_policies:
            policies = request.app.state.policies
            for name, origin in sorted(policies.origins().items()):
                if origin == "autopilot":
                    await policies.delete_pack(name)
                    removed.append(name)
            for domain in arena.domains.values():
                await policies.put_pack(domain.policy.name, domain.day_one_text)
                restored.append(domain.policy.name)
        arena.reset(clear_leaderboard=body.clear_leaderboard)
        return {
            "restored": restored,
            "removed": removed,
            "cleared_leaderboard": body.clear_leaderboard,
            "seconds": round(time.perf_counter() - start, 3),
        }

    return router
