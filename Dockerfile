# The API image. Multi-stage so the runtime layer carries no build tooling.
FROM python:3.12-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11.15 /uv /bin/uv
WORKDIR /app
# Dependencies first, so a source edit does not invalidate the dependency layer.
# LICENSE and README are copied with the manifest because the build backend reads both from
# `pyproject.toml`'s metadata. Found by building the image rather than by reading the file.
COPY pyproject.toml uv.lock LICENSE README.md ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
# A non-root user, created before anything is copied so the copies land with the right owner.
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
COPY --chmod=0755 deployment/entrypoint.sh /app/entrypoint.sh
USER app
EXPOSE 8000
# Migrations run at container start. The Dockerfile would normally argue against that — a process
# that migrates on boot races every other replica for the same DDL — and the reason it is acceptable
# here is a property of the plan rather than of the design: the free tier runs exactly one instance.
# Scale this to two and the race returns. Recorded in docs/deployment.md rather than resolved,
# because resolving it means paying for a release hook.
ENTRYPOINT ["/app/entrypoint.sh"]
