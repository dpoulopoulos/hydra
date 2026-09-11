# The same base and layering as the backend image. See backend/Dockerfile for
# why each step is the way it is; the differences here are that there is no
# database, so no prestart, and no alembic.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copying the two manifests on their own gets what matters: this layer is
# rebuilt when a dependency changes and reused when only the app does.
COPY ./pyproject.toml ./uv.lock /app/

RUN uv sync --frozen --no-install-project

ENV PYTHONPATH=/app/src

COPY ./src/hydra_mcp /app/src/hydra_mcp

RUN uv sync --frozen

# Drop to an unprivileged user for the same reason the backend does. This
# process forwards other people's credentials, so a code execution bug in it or
# in any of its dependencies should not also come with root in the container.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app/.venv

USER app

CMD ["python", "-m", "hydra_mcp.server"]
