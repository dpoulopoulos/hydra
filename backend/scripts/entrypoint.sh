#! /usr/bin/env bash

set -e
set -x

# Railway runs the migrations as its own pre-deploy step, so that a deployment
# of several replicas does not run them once per container. It sets
# RUN_PRESTART=false; the compose stack leaves it unset and prepares the
# database from here.
if [ "${RUN_PRESTART:-true}" = "true" ]; then
  echo "🔄 Running prestart.sh..."
  /app/scripts/prestart.sh
fi

# Reloading watches the source tree, which is only worth doing when that tree
# is synced in from a developer's machine.
reload=()
if [ "${ENVIRONMENT:-local}" = "local" ]; then
  reload=(--reload)
fi

# A host that puts a proxy in front picks the port and passes it in PORT.
echo "🚀 Starting FastAPI server..."
exec fastapi run src/app/main.py --host 0.0.0.0 --port "${PORT:-8000}" "${reload[@]}"
