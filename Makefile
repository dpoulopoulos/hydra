.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make dev           - Build and start everything, reloading on code changes"
	@echo "  make stop          - Stop all running services"
	@echo "  make clean         - Stop and remove all containers, networks, volumes and images"
	@echo "  make logs          - Follow the backend logs"
	@echo "  make logs-web      - Follow the frontend logs"
	@echo "  make format        - Format Python files"
	@echo "  make lint          - Scan Python files for linting errors"
	@echo "  make test-unit     - Run unit tests and report coverage"
	@echo "  make test-integration - Run the integration tests against a real Postgres"
	@echo ""
	@echo "  make web           - Start the frontend outside Docker (make dev runs it inside)"
	@echo "  make web-install   - Install frontend dependencies"
	@echo "  make web-build     - Type check and build the frontend"
	@echo "  make web-format    - Format frontend files"
	@echo "  make web-lint      - Scan frontend files for linting errors"
	@echo "  make web-test      - Check the production server config against a real Caddy"
	@echo "  make web-test-dev  - Check the dev image runs the web app unprivileged"
	@echo "  make web-test-unit - Run the frontend unit tests"
	@echo "  make web-api       - Regenerate the API client from the backend schema"
	@echo "  make web-api-check - Check the committed API client is up to date"

# The compose stack reads its configuration from .env, which is not committed.
# Fail with an actionable message rather than a variable error.
.PHONY: check-env
check-env:
	@test -f .env || { \
		echo ".env is missing. Create it with:"; \
		echo "  cp .env.example .env"; \
		exit 1; \
	}

# Starts Postgres, the mail catcher, the API and the web app together.
#
# Editing anything under backend/src/app or frontend/src is synced into the
# running container and picked up by that server's reloader. Editing a manifest
# or lock file rebuilds the image instead, since dependencies cannot be hot
# swapped.
.PHONY: dev
dev: check-env
	docker compose up --build --watch

.PHONY: stop
stop:
	docker compose down

.PHONY: clean
clean:
	docker compose down --rmi all -v

.PHONY: logs
logs:
	docker compose logs -f backend

.PHONY: logs-web
logs-web:
	docker compose logs -f frontend

.PHONY: format
format:
	bash ./backend/scripts/format.sh

.PHONY: lint
lint:
	bash ./backend/scripts/lint.sh

.PHONY: test-unit
test-unit:
	bash ./backend/scripts/test.sh

# Needs a Postgres to talk to: `make dev`, or anything else serving the
# POSTGRES_* settings in .env. The tests use a database of their own on that
# server, so they never touch the rows of a running stack.
.PHONY: test-integration
test-integration:
	bash ./backend/scripts/test-integration.sh

# --- frontend outside Docker -----------------------------------------------
# `make dev` already runs the web app in a container. These targets are for
# running it directly on the host instead, which is quicker for frontend-only
# work. The dev server proxies /api to the backend, so it still needs one
# running; set VITE_API_TARGET if it is not on port 8000.

.PHONY: web-install
web-install:
	cd frontend && pnpm install

.PHONY: web
web: web-install
	cd frontend && pnpm dev

.PHONY: web-build
web-build: web-install
	cd frontend && pnpm build

.PHONY: web-format
web-format:
	cd frontend && pnpm format

.PHONY: web-lint
web-lint:
	cd frontend && pnpm lint && pnpm typecheck

# Runs the production Caddyfile in a container and checks what it answers with.
# Needs Docker; it does not need the app to be built.
.PHONY: web-test
web-test:
	bash ./frontend/scripts/test-caddyfile.sh

# Runs the frontend unit tests in jsdom. No Docker and no backend needed.
# Builds the dev image and checks who it runs as, and that the dev server still
# serves what compose syncs into it. Needs Docker; the backend is not involved.
.PHONY: web-test-dev
web-test-dev:
	bash ./frontend/scripts/test-dev-image.sh

.PHONY: web-test-unit
web-test-unit: web-install
	cd frontend && pnpm test

# Re-dumps the OpenAPI schema from the backend and regenerates src/api.
.PHONY: web-api
web-api:
	cd frontend && pnpm generate:api

# Regenerates the client and fails if it differs from what is committed. This
# is what CI runs, so a forgotten web-api can be caught before pushing.
.PHONY: web-api-check
web-api-check:
	bash ./.github/scripts/check_api_client_synced.sh
