#!/usr/bin/env bash

set -e
set -x

cd "$(dirname "$0")/.."

# Only the unit tests: they mock the database session, so this needs no
# server. The integration tier next to them does, and runs from
# test-integration.sh instead.
uv run coverage run -m pytest tests/unit
uv run coverage report --omit=src/app/scripts/*
