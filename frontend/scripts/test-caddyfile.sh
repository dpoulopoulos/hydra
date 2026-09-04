#!/usr/bin/env bash
#
# Exercises frontend/Caddyfile against a real Caddy, so the production server's
# behaviour is checked rather than assumed.
#
# The app itself is not built for this: what is under test is the server
# configuration, so a stand-in tree of static files is enough. Docker is
# required, because Caddy is what the production image runs.

set -euo pipefail

cd "$(dirname "$0")/.."

image=caddy:2-alpine
container=hydra-caddyfile-test-$$
srv=$(mktemp -d)
failures=0

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  rm -rf "$srv"
}
trap cleanup EXIT

# A stand-in for the built app: an entry page, a bundle where Vite puts one,
# and nothing else.
mkdir -p "$srv/static"
echo '<!doctype html><title>hydra</title>' > "$srv/index.html"
echo 'export const answer = 42' > "$srv/static/app.js"

docker run --rm --detach --name "$container" \
  --publish 127.0.0.1:0:8080 \
  --volume "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  --volume "$srv:/srv:ro" \
  "$image" caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

base="http://$(docker port "$container" 8080/tcp | head -1)"

# The server needs a moment to bind before the first request.
for _ in $(seq 1 50); do
  curl --silent --fail --output /dev/null "$base/" && break
  sleep 0.2
done

# Reports one expectation, and remembers a failure without stopping: a run
# should list everything that is wrong, not only the first thing.
check() {
  local what=$1 expected=$2 actual=$3
  if [ "$expected" = "$actual" ]; then
    echo "ok   - $what"
  else
    echo "FAIL - $what: expected '$expected', got '$actual'"
    failures=$((failures + 1))
  fi
}

status() {
  curl --silent --output /dev/null --write-out '%{http_code}' "$base$1"
}

check "the entry page is served" 200 "$(status /)"
check "a bundle under /static is served" 200 "$(status /static/app.js)"
# Client side routing: an unknown path is a page of the app, not a 404.
check "an app route falls back to the entry page" 200 "$(status /budgets)"

if [ "$failures" -ne 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi

echo "all checks passed"
