#!/usr/bin/env bash
#
# Serves the built app the way production does -- the real files, the real
# Caddyfile, the real content security policy -- so that what the policy
# refuses can be seen rather than reasoned about.
#
# test-caddyfile.sh checks what the server answers with, against a stand-in
# tree of static files. It cannot check what a browser then does with the
# answer, and the part of the policy that is easiest to break is exactly that:
# `style-src-elem` takes only this origin and the page's nonce, so a dependency
# that builds a stylesheet while it runs has to carry the nonce or be refused.
# Nothing reports that but the browser.
#
# So this builds the app and serves it the way it will be served, which is what
# a browser needs before it can be pointed at anything. The backend is stood in
# for by a second container reading stub-backend.Caddyfile: what the screens
# show is not under test, but they have to have something to show.
#
# Docker is required, and Node with the dependencies installed.

set -euo pipefail

cd "$(dirname "$0")/.."

image=caddy:2-alpine
container=hydra-csp-test-$$
backend=hydra-csp-test-backend-$$
# A network of its own, because the two containers find each other by name and
# the default bridge resolves none.
network=hydra-csp-test-net-$$
failures=0

cleanup() {
  docker rm -f "$container" "$backend" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# The app itself, built the way the production image builds it. Nothing is
# reused from a previous run: a stale dist would have the browser walk a
# version of the app nobody is about to deploy.
echo "Building the app..."
rm -rf dist
# Quiet while it works, and everything it said when it does not: a build that
# failed is the whole answer, and the run has nothing left to check.
if ! build_output=$(pnpm build 2>&1); then
  echo "FAIL - the app did not build. pnpm build said:"
  echo "$build_output" | sed "s/^/  /"
  exit 1
fi

docker network create "$network" >/dev/null

docker run --detach --name "$backend" \
  --network "$network" \
  --volume "$PWD/scripts/stub-backend.Caddyfile:/etc/caddy/Caddyfile:ro" \
  "$image" caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

# Deliberately not --rm: a Caddyfile it cannot parse makes Caddy exit at once,
# and the container has to outlive that for its log to still be readable. The
# trap removes it either way.
docker run --detach --name "$container" \
  --network "$network" \
  --publish 127.0.0.1:0:8080 \
  --env "BACKEND_ORIGIN=http://$backend:80" \
  --volume "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  --volume "$PWD/dist:/srv:ro" \
  "$image" caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

# Says why the server is not there and stops, rather than letting the checks
# below run against nothing.
give_up() {
  local what=$1 who=${2:-$container}
  echo "FAIL - $what. $who said:"
  docker logs "$who" 2>&1 | sed "s/^/  /"
  exit 1
}

port=$(docker port "$container" 8080/tcp 2>/dev/null | head -1 || true)
[ -n "$port" ] || give_up "the server published no port"
base="http://$port"

# The server needs a moment to bind before the first request.
ready=""
for _ in $(seq 1 50); do
  if curl --silent --fail --output /dev/null "$base/"; then
    ready=yes
    break
  fi
  # A container that has already exited is never going to answer, so there is
  # nothing left to wait for.
  running=$(docker inspect --format "{{.State.Running}}" "$container" 2>/dev/null || true)
  [ "$running" = "true" ] || break
  sleep 0.2
done
[ -n "$ready" ] || give_up "the server never answered"

# The stub publishes no port of its own, so the only way to it is through the
# proxy. A failure here is the stub's, not the routing's, which is why it says
# so with the stub's log rather than leaving the walk to fail obscurely.
ready=""
for _ in $(seq 1 50); do
  if curl --silent --fail --output /dev/null "$base/api/v1/households/me"; then
    ready=yes
    break
  fi
  sleep 0.2
done
[ -n "$ready" ] || give_up "the backend stub never answered" "$backend"

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

# What is checked here is only that the browser will have the real app to walk
# -- the built entry page, the built bundles, and a backend behind /api. The
# headers themselves are test-caddyfile.sh's subject, and the rest of this run
# is the browser's.
check "the built entry page is served" 200 "$(status /)"
# The bundle the entry page asks for by name, so a build that emitted its files
# somewhere other than /static fails here rather than as a blank page.
entry_bundle=$(grep --only-matching '/static/[^"]*\.js' dist/index.html | head -1)
check "the entry page names a bundle under /static" "yes" \
  "$([ -n "$entry_bundle" ] && echo yes || echo no)"
check "that bundle is served" 200 "$(status "$entry_bundle")"
check "the backend stub answers through the proxy" 200 "$(status /api/v1/users/me)"

if [ "$failures" -ne 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi

echo "all checks passed"
