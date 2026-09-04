.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make dev         - Build and start the backend, reloading on code changes"
	@echo "  make stop        - Stop all running services"
	@echo "  make clean       - Stop and remove all containers, networks, volumes and images"
	@echo "  make logs        - Follow the backend logs"
	@echo "  make format      - Format Python files"
	@echo "  make lint        - Scan Python files for linting errors"
	@echo "  make test-unit   - Run unit tests and report coverage"
	@echo ""
	@echo "  make web         - Start the frontend dev server"
	@echo "  make web-install - Install frontend dependencies"
	@echo "  make web-build   - Type check and build the frontend"
	@echo "  make web-format  - Format frontend files"
	@echo "  make web-lint    - Scan frontend files for linting errors"
	@echo "  make web-api     - Regenerate the API client from the backend schema"

# The compose stack reads its configuration from .env, which is not committed.
# Fail with an actionable message rather than a variable error.
.PHONY: check-env
check-env:
	@test -f .env || { \
		echo ".env is missing. Create it with:"; \
		echo "  cp .env.example .env"; \
		exit 1; \
	}

# Editing anything under backend/src/app is synced into the running container
# and picked up by the server's reloader. Editing pyproject.toml or uv.lock
# rebuilds the image instead, since dependencies cannot be hot swapped.
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

.PHONY: format
format:
	bash ./backend/scripts/format.sh

.PHONY: lint
lint:
	bash ./backend/scripts/lint.sh

.PHONY: test-unit
test-unit:
	bash ./backend/scripts/test.sh

# --- frontend ---------------------------------------------------------------
# The dev server proxies /api to the backend, so run `make dev` alongside it.
# Set VITE_API_TARGET if the backend is not on port 8000.

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

# Re-dumps the OpenAPI schema from the backend and regenerates src/api.
.PHONY: web-api
web-api:
	cd frontend && pnpm generate:api
