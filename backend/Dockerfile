# The slim variant: psycopg is installed from the [binary] extra and every
# other dependency ships a wheel, so nothing is compiled here and the full
# image's toolchain, git and system libraries would only be CVE surface the app
# never uses.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.12.8 /uv /uvx /bin/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
#
# uv's own guide reaches for --mount here, both to cache its downloads and to
# read the manifests without copying them. Neither is available on every
# builder: Railway's accepts no mount but type=cache, and only with an id
# carrying its own s/<service id>-<path> prefix, which cannot come from a
# variable and so would mean writing one environment's id into this file.
#
# Copying the two manifests on their own gets the same thing that matters. This
# layer is rebuilt when a dependency changes and reused when only the app does.
COPY ./pyproject.toml ./uv.lock /app/

RUN uv sync --frozen --no-install-project

ENV PYTHONPATH=/app

COPY ./scripts /app/scripts

COPY ./alembic.ini /app/

COPY ./src/app /app/src/app

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN uv sync

RUN chmod +x /app/scripts/entrypoint.sh
RUN chmod +x /app/scripts/prestart.sh

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
