# syntax=docker/dockerfile:1.7

# ── Stage 1: build the homepage SPA (bun) ────────────────────────────────────
FROM oven/bun:1 AS homepage-builder

WORKDIR /home
COPY apps/homepage/package.json apps/homepage/bun.lock* ./
RUN bun install --frozen-lockfile

COPY apps/homepage/ ./
RUN bun run build


# ── Stage 2: resolve Python deps via uv ──────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS py-builder

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/ ./packages/
COPY apps/ ./apps/

RUN uv sync --no-dev --no-cache


# ── Stage 3: runtime ─────────────────────────────────────────────────────────
FROM python:3.13-slim-bookworm

WORKDIR /app
COPY --from=py-builder /app/.venv /app/.venv
COPY --from=py-builder /app/packages /app/packages
COPY --from=py-builder /app/apps /app/apps

# Drop the built homepage into the location the gateway serves at /
COPY --from=homepage-builder /home/dist/ /app/apps/maya-gateway/src/maya_gateway/static/

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/packages/maya-contracts/src:/app/packages/arena-core/src:/app/packages/maya-db/src:/app/packages/obs-client/src:/app/packages/fal-client/src:/app/apps/maya-gateway/src"

EXPOSE 8080
CMD ["maya-gateway"]
