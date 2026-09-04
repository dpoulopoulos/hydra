# hydra

A personal finance manager for a household: track spending, set monthly
budgets, and see where the money went, without the clutter.

Everything below the household is shared. Two people in one household see and
manage the same accounts, categories, budgets and transactions.

## What's inside

- `backend/` — a FastAPI app. See [backend/README.md](backend/README.md) for the
  data model, the layered architecture, and how to work on it.
- `frontend/` — a React app. See [frontend/README.md](frontend/README.md) for the
  stack, the generated API client, and the pages.
- `docker-compose.yaml` — runs the backend, Postgres, and a mail catcher together.
- `Makefile` — short commands for common tasks.
- `.github/workflows/` — CI checks on every pull request: format, lint, tests, migrations.

## What it does

| Feature | Notes |
|---|---|
| Households | Several people share one. A user belongs to exactly one. Owners manage members and invitations. |
| Accounts | Cash, current, savings, credit card. Balances are derived from the ledger, never stored. |
| Transactions | Expenses, income, and transfers between your own accounts. |
| Categories | Two levels deep, seeded on the first run, renameable and archivable. |
| Budgets | One limit per category per month. A limit on a parent covers everything under it. Nothing rolls over. |
| Recurring | Rent, subscriptions, standing transfers, recorded as each falls due. |
| Reports | Spending by category, spending over time, money in against money out, and the running total kept. |

Money is entered by hand. There is no bank sync, no multi-currency, and no split
transactions: leaving them out is what keeps the app small.

## Quick start

1. Copy the env file and fill in your own values:

   ```bash
   cp .env.example .env
   ```

2. Start the backend, Postgres and the mail catcher:

   ```bash
   make dev
   ```

   It watches the source tree, so most edits apply without a rebuild.

3. In a second terminal, start the web app:

   ```bash
   make web
   ```

4. Open it:

   - App: http://localhost:5173
   - API docs: http://localhost:8000/docs
   - Mailcatcher: http://localhost:1080

   Sign in with the `FIRST_SUPERUSER` credentials from your `.env`.

## Common commands

Run these from the repository root.

| Command | What it does |
|---------|--------------|
| `make dev` | Build and start the backend stack |
| `make stop` | Stop the stack |
| `make clean` | Stop the stack and remove containers, networks, volumes, and images |
| `make logs` | Follow the backend logs |
| `make format` | Format the Python code |
| `make lint` | Check types and lint the Python code |
| `make test-unit` | Run the unit tests and show coverage |
| `make web` | Start the web app's dev server |
| `make web-build` | Type check and build the web app |
| `make web-format` | Format the frontend code |
| `make web-lint` | Type check and lint the frontend code |
| `make web-api` | Regenerate the API client from the backend's schema |

## How the two halves fit together

The frontend's API client is **generated** from the backend's OpenAPI schema, so
every request and response is typed from the source of truth. After changing the
API, run `make web-api` and the client catches up.

In development the web app proxies `/api` to the backend, so the browser sees a
single origin and CORS never comes into it. If the backend is not on port 8000,
set `VITE_API_TARGET`.

## Three decisions worth knowing before changing things

**Money is an integer count of minor units** on both sides, in fields named
`*_minor`. Amounts are exact, so a budget comparison needs no tolerance. How many
minor units make a major one is a property of the currency, so neither half
divides by 100 inline.

**An amount is always a positive magnitude; the meaning lives in `kind`.** A
sign convention cannot be enforced by a database constraint, so a mis-signed row
would be silently wrong forever, and a transfer has no natural single sign. The
sign is applied once, in SQL. A transfer is therefore one row with a counter
account, which is why every spending report is simply `kind = 'EXPENSE'` and a
transfer can never leak into spending.

**Account balances are computed, never stored.** A stored balance is a cache with
no invalidation story that survives back-dated edits, re-pointed transfers and
recurring runs, and a balance that has quietly drifted is the most damaging bug a
finance app can have.
