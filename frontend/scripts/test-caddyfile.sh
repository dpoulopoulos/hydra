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

# Deliberately not --rm: a Caddyfile it cannot parse makes Caddy exit at once,
# and the container has to outlive that for its log to still be readable. The
# trap removes it either way.
docker run --detach --name "$container" \
  --publish 127.0.0.1:0:8080 \
  --volume "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" \
  --volume "$srv:/srv:ro" \
  "$image" caddy run --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

# Says why the server is not there and stops, rather than letting the checks
# below run against nothing: they would each report an empty response, which
# names none of the config errors that are the likely cause.
give_up() {
  echo "FAIL - $1. Caddy said:"
  docker logs "$container" 2>&1 | sed "s/^/  /"
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

# The last value of a response header, named case insensitively, or the empty
# string when the response carries no such header.
header() {
  curl --silent --head "$base$2" \
    | tr -d '\r' \
    | grep --ignore-case "^$1:" \
    | sed "s/^[^:]*: *//" \
    | tail -1
}

check "the entry page is served" 200 "$(status /)"
check "a bundle under /static is served" 200 "$(status /static/app.js)"
# Client side routing: an unknown path is a page of the app, not a 404.
check "an app route falls back to the entry page" 200 "$(status /budgets)"

csp="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"

# The session token lives in localStorage, so the browser's script execution
# controls are what stands between an injected script and the token.
check "the entry page carries a content security policy" "$csp" "$(header content-security-policy /)"
check "the entry page forbids MIME sniffing" "nosniff" "$(header x-content-type-options /)"
# Reset, verification and invite links carry a single use token in the query
# string, which must not leak to another origin in a Referer header.
check "the entry page sends no referrer" "no-referrer" "$(header referrer-policy /)"
check "the entry page refuses to be framed" "DENY" "$(header x-frame-options /)"
check "the entry page asserts HSTS" "max-age=31536000; includeSubDomains" "$(header strict-transport-security /)"
check "the server does not name itself" "" "$(header server /)"

# The headers belong to every response, not only to the entry page: a bundle
# and an app route are served by different handlers.
check "a bundle carries the policy too" "$csp" "$(header content-security-policy /static/app.js)"
check "an app route carries the policy too" "$csp" "$(header content-security-policy /budgets)"

if [ "$failures" -ne 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi

echo "all checks passed"
