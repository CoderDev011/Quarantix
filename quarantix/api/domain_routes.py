"""Domain generator routes (F19). Admin only; nothing goes live before confirm.

No `from __future__ import annotations`: FastAPI resolves these type hints at import.
"""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from quarantix.api.schemas import DraftOut
from quarantix.domaingen.generator import DomainGenerator, GenerationError


class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(max_length=400)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": code, "message": message, "details": {}}, status_code=status)


def domain_router(require_admin: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/v1/domains", dependencies=[Depends(require_admin)])

    def generator(request: Request) -> DomainGenerator | None:
        return getattr(request.app.state, "domain_generator", None)

    @router.post("/generate", status_code=201, response_model=DraftOut)
    async def generate(request: Request, body: GenerateIn) -> JSONResponse:
        gen = generator(request)
        if gen is None:
            return _error(503, "generator_unavailable", "The domain generator is not configured.")
        try:
            draft = await gen.generate(body.description)
        except GenerationError as exc:
            return _error(422, "generation_failed", str(exc))
        return JSONResponse(draft.to_wire(), status_code=201)

    @router.get("/drafts/{draft_id}", response_model=DraftOut)
    async def get_draft(request: Request, draft_id: str) -> JSONResponse:
        gen = generator(request)
        draft = gen.drafts.get(draft_id) if gen is not None else None
        if draft is None:
            return _error(404, "not_found", "no such draft")
        return JSONResponse(draft.to_wire())

    @router.post("/drafts/{draft_id}/confirm", response_model=DraftOut)
    async def confirm(request: Request, draft_id: str) -> JSONResponse:
        """A person confirmed the labels: load the pack, seed its policy, show its goals."""
        gen = generator(request)
        if gen is None or draft_id not in gen.drafts:
            return _error(404, "not_found", "no such draft")
        try:
            draft = gen.confirm(draft_id)
        except GenerationError as exc:
            return _error(409, "not_confirmable", str(exc))
        domain = draft.domain
        assert domain is not None
        if domain.name in request.app.state.domains:
            return _error(409, "name_taken", f"a domain named {domain.name!r} is already loaded")
        await request.app.state.policies.put_pack(domain.policy.name, domain.day_one_text)
        request.app.state.domains[domain.name] = domain
        arena: Any = request.app.state.arena
        if arena is not None:
            arena.add_domain(domain)
        request.app.state.agents.known = sorted({*request.app.state.agents.known, domain.agent})
        return JSONResponse({**draft.to_wire(), "agent": domain.agent})

    return router
