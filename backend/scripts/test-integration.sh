#! /usr/bin/env bash

set -e
set -x

cd "$(dirname "$0")/.."

# These tests talk to a real Postgres, unlike the unit suite, which mocks the
# session. They connect to the server the settings point at and use a database
# of their own next to it, so they never touch the rows of a running stack.
# `make dev` or the compose db service is enough to have one.
uv run pytest tests/integration
