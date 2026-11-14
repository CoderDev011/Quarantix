# One image for every Quarantix Python service (F23). Different services = different commands.
# Build:  docker build -t quarantix:demo .

# ---- stage 1: build the console (React) ---------------------------------------------
FROM node:22-slim AS dashboard
WORKDIR /build
RUN npm install --global pnpm@10.34.9
COPY dashboard/package.json dashboard/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY dashboard/ ./
RUN pnpm build

# ---- stage 2: the Python runtime ------------------------------------------------------
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Dependencies first (cached unless the lockfile changes), then the project itself.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY quarantix/ ./quarantix/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

COPY cassettes/ ./cassettes/
COPY domains/ ./domains/
COPY redteam/ ./redteam/
COPY --from=dashboard /build/dist/ ./quarantix/api/static/

# Never run as root. /app/data holds the SQLite database (mount a volume there).
RUN useradd --system --uid 10001 --home /app quarantix \
    && mkdir -p /app/data && chown -R quarantix /app/data
USER quarantix

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "--factory", "quarantix.api.app:app_from_env", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
