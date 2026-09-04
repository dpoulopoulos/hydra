#!/usr/bin/env bash

set -e
set -x

cd "$(dirname "$0")/.."

uv run coverage run -m pytest tests/
uv run coverage report --omit=src/app/scripts/*
