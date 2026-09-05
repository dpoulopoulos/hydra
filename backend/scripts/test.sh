#!/usr/bin/env bash

set -e
set -x

cd "$(dirname "$0")/.."

# Only the unit tests: they mock the database session, so this needs no
# server. The integration tier next to them does, and runs from
# test-integration.sh instead.
uv run coverage run -m pytest tests/unit
# The threshold sits just under where the suite is, so an ordinary refactor
# does not have to move it, while deleting a test or shipping an unexercised
# branch fails here rather than being noticed a release later. Raise it when
# the figure it guards has risen for good.
uv run coverage report --omit=src/app/scripts/* --fail-under=92
