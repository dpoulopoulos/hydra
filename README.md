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
- `.railway/railway.ts` — the deployed project: which services exist, how they
  are wired, and where each builds from.
- `DEPLOY.md` — deploying to Railway, step by step.
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

2. Start everything, the web app, the API, Postgres and a mail catcher:

   ```bash
   make dev
   ```

   It watches both source trees. Editing `backend/src/app` or `frontend/src`
   reloads in place; editing a manifest or lock file rebuilds that image.

3. Open it:

   - App: http://localhost:5173
   - API docs: http://localhost:8000/docs
   - Mailcatcher: http://localhost:1080

   Sign in with the `FIRST_SUPERUSER` credentials from your `.env`.

## Common commands

Run these from the repository root.

| Command | What it does |
|---------|--------------|
| `make dev` | Build and start everything, reloading on changes |
| `make stop` | Stop the stack |
| `make clean` | Stop the stack and remove containers, networks, volumes, and images |
| `make logs` | Follow the backend logs |
| `make logs-web` | Follow the frontend logs |
| `make format` | Format the Python code |
| `make lint` | Check types and lint the Python code |
| `make test-unit` | Run the unit tests and show coverage |
| `make web` | Run the web app on the host instead of in Docker |
| `make web-build` | Type check and build the web app |
| `make web-format` | Format the frontend code |
| `make web-lint` | Type check and lint the frontend code |
| `make web-api` | Regenerate the API client from the backend's schema |

## Deploying to Railway

Three services, described in one file, [`.railway/railway.ts`](.railway/railway.ts).

| Service | What it is | Public? |
|---|---|---|
| `web` | The compiled web app, served by Caddy, which also forwards `/api` and `/assets` to the backend over the private network. | Yes. This is the app's address. |
| `backend` | The FastAPI app. | No. Reachable only through `web`. |
| `postgres` | Railway's managed Postgres. | No. |

One public origin means the browser never makes a cross-site request, so CORS
never comes into it and the API is not exposed on its own.

Both services build from this repository, so **pushing to `main` redeploys
them**. Editing `.railway/railway.ts` is the exception: run `railway config
plan` and `railway config apply`, because a push does not read that file.

**[DEPLOY.md](DEPLOY.md) is the step by step**, for a first deployment and for
what to check when something is wrong.

One thing worth knowing before you read it: Railway blocks outgoing SMTP below
its Pro plan, so the deployed app posts to the Resend API over HTTPS instead.
That is what `EMAIL_PROVIDER=resend` selects. Locally the setting stays `smtp`
and mail lands in the mail catcher, unchanged.

## How the two halves fit together

The frontend's API client is **generated** from the backend's OpenAPI schema, so
every request and response is typed from the source of truth. After changing the
API, run `make web-api` and the client catches up.

In development the web app proxies `/api` to the backend, so the browser sees a
single origin and CORS never comes into it. Inside the compose stack that target
is the `backend` service; running the web app on the host it defaults to
`localhost:8000`, overridable with `VITE_API_TARGET`.

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
