#!/bin/sh -e
set -x

cd "$(dirname "$0")/.."

uv run ruff check src scripts tests --fix
uv run ruff format src scripts tests
