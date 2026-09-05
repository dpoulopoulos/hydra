#!/usr/bin/env bash
#
# Exercises the `dev` stage of frontend/Dockerfile, which is the image the
# compose stack builds by name and the one developers run all day.
#
# What is under test is who the container runs as. A dev server holding the
# repository's source under /app should not be root, and everything the server
# writes to while it runs -- the install tree, Vite's cache, the package
# manager's home -- has to stay writable for whoever it does run as.
#
# Docker is required. The backend is not: the dev server starts without one and
# only proxies /api to it.

set -euo pipefail

cd "$(dirname "$0")/.."

image=hydra-frontend-dev-test:$$
container=hydra-frontend-dev-test-$$
failures=0

cleanup() {
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker image rm -f "$image" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build --target dev --tag "$image" . >/dev/null

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

# Runs a command in a throwaway container of the image, as the image's own
# user, and prints what it said. A failing command reports as the empty string
# rather than ending the run.
in_image() {
  docker run --rm --entrypoint sh "$image" -c "$1" 2>/dev/null || true
}

check "the image does not run as root" "0" "$(in_image 'test "$(id -u)" -ne 0 && echo 0')"
check "the image runs as the node user the base image ships" "node" "$(in_image 'id -un')"

# The install tree is written during the build and again whenever Vite
# pre-bundles a dependency into node_modules/.vite, so it has to belong to the
# user the server runs as.
check "the install tree belongs to that user" "node" "$(in_image 'stat -c %U /app/node_modules')"
check "the install tree is writable" "yes" "$(in_image 'test -w /app/node_modules && echo yes')"

# corepack downloads pnpm into HOME on first use, and pnpm keeps its store
# there too. A HOME pointing at root's would fail the moment either wrote.
check "HOME belongs to that user" "node" "$(in_image 'stat -c %U "$HOME"')"
check "HOME is writable" "yes" "$(in_image 'test -w "$HOME" && echo yes')"

# The package manager still resolves as that user: corepack's shim reads the
# packageManager field and needs its cache to already be there, offline.
check "pnpm runs as that user" "10.15.0" "$(in_image 'pnpm --version')"

# --- the running dev server -------------------------------------------------

docker run --rm --detach --name "$container" \
  --env VITE_IN_CONTAINER=true \
  --publish 127.0.0.1:0:5173 \
  "$image" >/dev/null

base="http://$(docker port "$container" 5173/tcp | head -1)"

# Vite takes a moment to bind, and longer on the first run of a cold image.
for _ in $(seq 1 150); do
  curl --silent --fail --output /dev/null "$base/" && break
  sleep 0.2
done

status() {
  curl --silent --output /dev/null --write-out '%{http_code}' "$base$1"
}

check "the dev server serves the entry page" 200 "$(status /)"
check "the dev server transforms a module" 200 "$(status /src/main.tsx)"
# The slim image ships no ps, so the owner of pid 1 is read from /proc, where
# the entry belongs to the user the process runs as.
check "the dev server process is not root" "node" \
  "$(docker exec "$container" stat -c %U /proc/1 2>/dev/null)"

# What `docker compose watch` does to a running container: the daemon writes
# the changed file into /app from outside the container, as root. The server
# has to be able to read and serve what arrives.
tmp=$(mktemp -d)
trap 'cleanup; rm -rf "$tmp"' EXIT
echo 'export const synced = 42' > "$tmp/synced.ts"
docker cp "$tmp/synced.ts" "$container:/app/src/synced.ts"

check "a synced file is served" 200 "$(status /src/synced.ts)"

if [ "$failures" -ne 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi

echo "all checks passed"
