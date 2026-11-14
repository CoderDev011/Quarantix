"""Control-plane HTTP API (F13).

Run: `uvicorn --factory quarantix.api.app:app_from_env --workers 1` (settings from env).
One process by design: sequence numbers, the event bus and approvals live here.
Every error uses the contract shape {error, message, details} (contracts §17).
No `from __future__ import annotations` here: FastAPI resolves the route type
hints at definition time, including the auth aliases local to `create_app`.
"""

import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sse_starlette.sse import EventSourceResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from quarantix.api.auth import Credentials, bearer
from quarantix.api.bus import EventBus
from quarantix.api.policies import PolicyService
from quarantix.api.schemas import AgentsPage, ApprovalsPage, EventsPage, SessionIn
from quarantix.api.settings import Settings
from quarantix.api.sse import event_stream
from quarantix.api.store import Store
from quarantix.core.contracts import Event
from quarantix.core.redact import preview
from quarantix.engine.approvals import ApprovalNotPending, InProcessApprovalBroker
from quarantix.engine.policy import PolicyError

MAX_BATCH = 500
_SEEN_IDS = 100_000
ADMIN_COOKIE = "qx_admin"


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


def _error(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": code, "message": message, "details": details or {}}, status_code=status
    )


def resume_point(*, since: int, last_event_id: str | None) -> int:
    """Where a live stream resumes: the browser's Last-Event-ID wins over `since`."""
    if last_event_id is not None and last_event_id.strip().isdigit():
        return int(last_event_id.strip())
    return since


def _etag_version(header: str | None) -> str | None:
    if not header:
        return None
    return header.strip().removeprefix("W/").strip('"') or None


class AgentDirectory:
    def __init__(self, agents: list[str]) -> None:
        self.last_seen: dict[str, float] = {}
        self.sdk_version: dict[str, str] = {}
        self.known = agents

    def seen(self, agent: str, sdk_version: str | None) -> None:
        self.last_seen[agent] = time.monotonic()
        if sdk_version:
            self.sdk_version[agent] = sdk_version[:32]


def create_app(settings: Settings) -> FastAPI:
    credentials = Credentials(settings.admin_token, settings.agent_keys)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store = Store(settings.database_url)
        await store.create()
        bus = EventBus(store, flush_interval=settings.flush_interval)
        await bus.start()
        policies = PolicyService(store)
        await policies.load()
        app.state.store, app.state.bus, app.state.policies = store, bus, policies
        app.state.approvals = InProcessApprovalBroker()
        app.state.agents = AgentDirectory(credentials.agents)
        app.state.seen_ids = OrderedDict()
        try:
            yield
        finally:
            await bus.stop()
            await store.close()

    app = FastAPI(title="Quarantix control plane", version="0.1.0", lifespan=lifespan)

    # ---------------------------------------------------------------- errors and limits

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
        return _error(exc.status_code, code.get(exc.status_code, "error"), str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(
            422, "invalid_request", "the request is invalid", {"errors": exc.errors()[:10]}
        )

    @app.middleware("http")
    async def _body_limit(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > settings.max_body_bytes:
            return _error(
                413, "too_large", f"request bodies are limited to {settings.max_body_bytes} bytes"
            )
        return await call_next(request)

    # ---------------------------------------------------------------- auth dependencies

    def require_agent(authorization: Annotated[str | None, Header()] = None) -> str:
        agent = credentials.agent_for(bearer(authorization))
        if agent is None:
            raise ApiError(401, "unauthorized", "a valid agent key is required")
        return agent

    def require_admin(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        token: Annotated[str | None, Query()] = None,
    ) -> None:
        # EventSource cannot set headers, so the stream also accepts a cookie or ?token=.
        candidate = bearer(authorization) or request.cookies.get(ADMIN_COOKIE) or token
        if not credentials.is_admin(candidate):
            raise ApiError(401, "unauthorized", "the admin token is required")

    Admin = Depends(require_admin)

    # ---------------------------------------------------------------- health

    @app.get("/healthz")
    async def health(request: Request) -> dict[str, Any]:
        return {"status": "ok", "bundle_version": request.app.state.policies.version}

    # ---------------------------------------------------------------- events

    @app.post("/v1/events:batch")
    async def upload_events(
        request: Request, agent: Annotated[str, Depends(require_agent)]
    ) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            raise ApiError(400, "invalid_json", "the body must be JSON") from None
        items = body.get("events") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise ApiError(400, "invalid_request", 'send {"events": [...]}')
        if len(items) > MAX_BATCH:
            raise ApiError(413, "too_large", f"at most {MAX_BATCH} events per batch")
        seen: OrderedDict[str, None] = request.app.state.seen_ids
        accepted, duplicates, rejected = 0, 0, []
        for index, raw in enumerate(items):
            try:
                event = Event.from_wire(raw)
            except ValueError as exc:
                rejected.append({"index": index, "error": str(exc)[:200]})
                continue
            if event.agent != agent:
                rejected.append(
                    {"index": index, "error": f"event agent {event.agent!r} does not match the key"}
                )
                continue
            if event.event_id in seen:  # an SDK retry: never broadcast or store twice
                duplicates += 1
                continue
            seen[event.event_id] = None
            if len(seen) > _SEEN_IDS:
                seen.popitem(last=False)
            request.app.state.bus.emit(event)
            accepted += 1
        return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}

    @app.get("/v1/events", dependencies=[Admin], response_model=EventsPage)
    async def history(
        request: Request,
        since: int = 0,
        agent: str | None = None,
        run_id: str | None = None,
        kind: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> dict[str, Any]:
        events = await request.app.state.store.events_since(
            since, agent=agent, run_id=run_id, kinds=kind, limit=limit
        )
        return {"events": events}

    @app.get("/v1/events/stream", dependencies=[Admin])
    async def stream(
        request: Request,
        since: int = 0,
        agent: str | None = None,
        run_id: str | None = None,
        kind: Annotated[list[str] | None, Query()] = None,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> EventSourceResponse:
        start = resume_point(since=since, last_event_id=last_event_id)
        items = event_stream(
            request.app.state.bus, since=start, agent=agent, run_id=run_id, kinds=kind
        )
        return EventSourceResponse(items, ping=15)

    # ---------------------------------------------------------------- policies

    @app.get("/v1/policies/packs", dependencies=[Admin])
    async def list_packs(request: Request) -> dict[str, Any]:
        policies: PolicyService = request.app.state.policies
        names = sorted(name for name in policies.texts() if not name.startswith("_"))
        return {"bundle_version": policies.version, "packs": [{"name": n} for n in names]}

    @app.get("/v1/policies/packs/{name}", dependencies=[Admin])
    async def get_pack(request: Request, name: str) -> PlainTextResponse:
        text = request.app.state.policies.texts().get(name)
        if text is None:
            raise ApiError(404, "not_found", f"no pack named {name!r}")
        return PlainTextResponse(text, media_type="application/yaml")

    @app.put("/v1/policies/packs/{name}", dependencies=[Admin])
    async def put_pack(request: Request, name: str) -> dict[str, Any]:
        text = (await request.body()).decode("utf-8", errors="replace")
        try:
            version = await request.app.state.policies.put_pack(name, text)
        except PolicyError as exc:
            raise ApiError(
                422, "invalid_policy", exc.message, {"line": exc.line, "column": exc.column}
            ) from None
        except ValueError as exc:
            raise ApiError(422, "invalid_policy", str(exc)) from None
        return {"name": name, "bundle_version": version}

    @app.post("/v1/policies/validate", dependencies=[Admin])
    async def validate_pack(request: Request) -> dict[str, Any]:
        from quarantix.engine.policy import compile_pack

        try:
            compile_pack((await request.body()).decode("utf-8", errors="replace"))
        except PolicyError as exc:
            raise ApiError(
                422, "invalid_policy", exc.message, {"line": exc.line, "column": exc.column}
            ) from None
        return {"valid": True}

    @app.get("/v1/policies/bundle")
    async def bundle(
        request: Request,
        agent: Annotated[str, Depends(require_agent)],
        for_agent: Annotated[str, Query(alias="agent")],
        wait: Annotated[float, Query(ge=0)] = 25.0,
        if_none_match: Annotated[str | None, Header()] = None,
        x_quarantix_sdk: Annotated[str | None, Header()] = None,
    ) -> Response:
        if for_agent != agent:
            raise ApiError(403, "forbidden", "an agent can only sync its own bundle")
        request.app.state.agents.seen(agent, x_quarantix_sdk)  # every poll is a heartbeat
        policies: PolicyService = request.app.state.policies
        known = _etag_version(if_none_match)
        await policies.wait_for_change(known, min(wait, settings.long_poll_max_s))
        request.app.state.agents.seen(agent, x_quarantix_sdk)
        headers = {"ETag": f'"{policies.version}"'}
        if known == policies.version:
            return Response(status_code=304, headers=headers)
        return JSONResponse(policies.wire_bundle(), headers=headers)

    # ---------------------------------------------------------------- agents

    @app.get("/v1/agents", dependencies=[Admin], response_model=AgentsPage)
    async def agents(request: Request) -> dict[str, Any]:
        directory: AgentDirectory = request.app.state.agents
        policies: PolicyService = request.app.state.policies
        now = time.monotonic()
        return {
            "agents": [
                {
                    "name": name,
                    "online": now - directory.last_seen.get(name, float("-inf"))
                    < settings.online_window_s,
                    "mode": policies.mode(name),
                    "policy_version": policies.version,
                    "sdk_version": directory.sdk_version.get(name),
                }
                for name in sorted(directory.known)
            ]
        }

    @app.put("/v1/agents/{agent}/mode", dependencies=[Admin])
    async def set_mode(request: Request, agent: str) -> dict[str, Any]:
        body = await request.json()
        try:
            version = await request.app.state.policies.set_mode(agent, str(body.get("mode", "")))
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from None
        return {"agent": agent, "mode": body["mode"], "bundle_version": version}

    # ---------------------------------------------------------------- approvals inbox

    @app.get("/v1/approvals", dependencies=[Admin], response_model=ApprovalsPage)
    async def approvals(request: Request) -> dict[str, Any]:
        broker: InProcessApprovalBroker = request.app.state.approvals
        now = time.monotonic()
        return {
            "approvals": [
                {
                    "id": item.approval_id,
                    "run_id": item.request.run_id,
                    "agent": item.request.agent,
                    "tool": item.request.tool,
                    "rule": item.decision.rule,
                    "reason": item.decision.reason,
                    "args": {
                        name: preview(arg.value, arg.label, arg.evidence)
                        for name, arg in item.request.args.items()
                    },
                    "age_s": round(now - item.created, 1),
                }
                for item in broker.pending()
            ]
        }

    @app.post("/v1/approvals/{approval_id}/resolve", dependencies=[Admin])
    async def resolve(request: Request, approval_id: str) -> dict[str, Any]:
        body = await request.json()
        try:
            request.app.state.approvals.resolve(
                approval_id, body.get("verdict"), body.get("scope", "once")
            )
        except ApprovalNotPending:
            raise ApiError(409, "conflict", "this approval is no longer pending") from None
        except ValueError as exc:
            raise ApiError(422, "invalid_request", str(exc)) from None
        return {"id": approval_id, "verdict": body.get("verdict")}

    # ---------------------------------------------------------------- console login (cookie)

    @app.post("/v1/session")
    async def login(request: Request, body: SessionIn) -> JSONResponse:
        """Swap the admin token for an HttpOnly cookie, so the live stream never needs ?token=."""
        if not credentials.is_admin(body.token):
            raise ApiError(401, "unauthorized", "the admin token is not valid")
        response = JSONResponse({"ok": True})
        response.set_cookie(
            ADMIN_COOKIE,
            body.token,
            max_age=12 * 3600,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    @app.delete("/v1/session")
    async def logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(ADMIN_COOKIE, path="/")
        return response

    # ---------------------------------------------------------------- the built dashboard (last!)

    _serve_dashboard(app, settings)
    return app


_NOT_BUILT = (
    "the dashboard is not built: run `pnpm build` in dashboard/ and copy dist/ to "
    "quarantix/api/static (or set AGENTWALL_DASHBOARD_DIR)"
)


def _serve_dashboard(app: FastAPI, settings: Settings) -> None:
    """Serve the built single-page app, with every non-API path falling back to index.html.

    Registered after all API routes, so API paths always win; unknown API paths stay JSON 404s.
    Files are only ever served from inside the dashboard folder (no path traversal).
    """
    root = settings.dashboard_dir.resolve() if settings.dashboard_dir else None
    index = root / "index.html" if root else None

    @app.get("/{path:path}", include_in_schema=False)
    async def dashboard(path: str) -> FileResponse:
        if path == "v1" or path.startswith(("v1/", "healthz", "openapi.json", "docs")):
            raise ApiError(404, "not_found", f"no API route for /{path}")
        if root is None or index is None or not index.is_file():
            raise ApiError(404, "not_found", _NOT_BUILT)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        if "." in path.rsplit("/", 1)[-1]:  # a missing asset: never answer with the page
            raise ApiError(404, "not_found", f"no file /{path}")
        return FileResponse(index)


def app_from_env() -> FastAPI:
    """Uvicorn factory: fails loudly if required settings (the admin token) are missing."""
    return create_app(Settings.from_env())


__all__ = ["ApiError", "app_from_env", "create_app", "resume_point"]
