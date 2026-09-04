#!/usr/bin/env bash
#
# Verify that the committed API client is what the backend schema generates.
#
# `make web-api` is a manual step, so an API change can be merged with a stale
# client: the committed client still compiles against the committed pages, and
# nothing else in CI looks at the backend schema. Regenerating and diffing is
# the only thing that catches it.
#
# Exits non-zero, showing the diff, if openapi.json or src/api would change.

set -e

cd "$(dirname "$0")/../../frontend"

pnpm generate:api

# --porcelain rather than `diff --exit-code`: it reports a client file that is
# new, and not only one that changed, without touching the index.
if [ -n "$(git status --porcelain -- openapi.json src/api)" ]; then
  git --no-pager diff -- openapi.json src/api
  echo
  echo "The API client is out of date. Run 'make web-api' and commit the result." >&2
  exit 1
fi

echo "The API client matches the backend schema."
