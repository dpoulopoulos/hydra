# Backend Template

A starter kit for backend apps.

Use this repo as a template. Click "Use this template" on GitHub, or clone it and rename things to fit your project.

## What's inside

- `backend/` — a FastAPI app. See [backend/README.md](backend/README.md) for the app's design and how to work on it.
- `docker-compose.yaml` — runs the backend, Postgres, and a mail catcher together.
- `Makefile` — short commands for common tasks.
- `.github/workflows/` — CI checks that run on every pull request (format, lint, tests, migrations).

## Quick start

1. Copy the env file and fill in your own values:

   ```bash
   cp .env.example .env
   ```

2. Start the stack:

   ```bash
   make dev
   ```

   This builds the backend image and starts it with Postgres and mailcatcher. It watches your code, so most edits
   apply without a rebuild.

3. Open the app:

   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs
   - Mailcatcher: http://localhost:1080

## Common commands

Run these from the repository root.

| Command | What it does |
|---------|--------------|
| `make dev` | Build and start the stack |
| `make stop` | Stop the stack |
| `make clean` | Stop the stack and remove containers, networks, volumes, and images |
| `make logs` | Follow the backend logs |
| `make format` | Format the Python code |
| `make lint` | Check types and lint the Python code |
| `make test-unit` | Run the unit tests and show coverage |

## Using this as a template

To start a new project from this repo:

1. Update `PROJECT_NAME` and `PROJECT_ID` in `.env.example`.
2. Update the project name in `backend/pyproject.toml`.
3. Read [backend/README.md](backend/README.md) for how the app is structured, and add your own models, routes, and
   services from there.
