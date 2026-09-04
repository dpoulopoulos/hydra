#! /usr/bin/env bash

set -e
set -x

# Let the DB start
uv run python src/app/scripts/backend_pre_start.py

# Run migrations
uv run alembic upgrade head

# Create initial data in DB
uv run python src/app/scripts/initial_data.py
