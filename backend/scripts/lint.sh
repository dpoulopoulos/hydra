#!/usr/bin/env bash

set -e
set -x

cd "$(dirname "$0")/.."

uv run mypy src tests

uv run ruff check src tests
