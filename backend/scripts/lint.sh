#!/usr/bin/env bash

set -e
set -x

cd "$(dirname "$0")/.."

uv run mypy src

# tests is linted but not type checked: the suite leans on MagicMock, which
# strict mypy has little to say about. See #107.
uv run ruff check src tests
