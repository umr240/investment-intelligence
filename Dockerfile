# Reproducibility and CI parity only. ADR-040 decided a local UI; the SQLite DB
# is mounted, never baked in (SECURITY & PRIVACY §7).
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependency layer first so source edits don't invalidate the install.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Secrets arrive at runtime via --env-file, never ENV or a COPY of .env.
ENTRYPOINT []
CMD ["invest", "--help"]
