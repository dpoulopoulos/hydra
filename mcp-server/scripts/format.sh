#!/bin/sh -e
set -x

cd "$(dirname "$0")/.."

uv run ruff check src --fix
uv run ruff format src
