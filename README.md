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
- `.github/workflows/` — CI checks on every pull request, over both halves:
  format, lint, tests, migrations, the frontend build, and whether the generated
  API client is still in sync.

## What it does

| Feature      | Notes                                                                                                                                                                                                              |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Households   | Several people share one. A user belongs to exactly one. Owners manage members and invitations.                                                                                                                    |
| Accounts     | Cash, current, savings, credit card. Balances are derived from the ledger, never stored.                                                                                                                           |
| Transactions | Expenses, income, and transfers between your own accounts.                                                                                                                                                         |
| Categories   | Two levels deep, seeded on the first run, renameable and archivable.                                                                                                                                               |
| Budgets      | One limit per category per month. A limit on a parent covers everything under it. Nothing rolls over.                                                                                                              |
| Recurring    | Rent, subscriptions, standing transfers, recorded as each falls due.                                                                                                                                               |
| Reports      | Spending by category, spending over time, money in against money out, and the running total kept.                                                                                                                  |
| Investments  | ETFs and shares, recorded as buys and sells. Prices come from EODHD on a free key; the portfolio is valued in the household's currency.                                                                            |
| Income       | For work paid session by session. Clients, the hours they attend, what they still owe, and an estimate of what the coming month will bring. Client names are encrypted in the browser under each person's own PIN. |

The Income section is for anyone paid by the hour rather than by the month: a
psychologist, a tutor, a coach.

Most of such a practice is standing appointments, so a client carries how often
they are seen: every week, every other Wednesday, four days a week on Monday,
Tuesday, Thursday and Friday, once a month. A weekly pattern can name the days
outright, which is the case one appointment a week cannot express and intensive
work needs. Naming none of them is the ordinary case and means "the weekday
this started on", so the simple client stays simple.

The pattern is pinned to the date it began. For a monthly client that fixes the
day of the month, and a schedule on the 31st comes back to the 31st after
February rather than sticking on the 28th. For a weekly one it fixes which
weeks count, so "every other week" keeps its rhythm however far ahead you look.
It reuses the recurrence vocabulary the Recurring page already had, because it
is the same question and that arithmetic is written and tested; the weekday
sets sit in their own module rather than being pushed into it, so recurring
rules gain nothing they did not ask for. Somebody seen as and when carries no
pattern at all, which is a real answer rather than a missing one.

Beyond that, the section rests on two ideas.

The first is that a session carries two separate facts, and squashing them
together loses one of them. What happened to the hour — attended, missed,
called off, still ahead — is not the same question as whether the money arrived.
A client can come and pay next week. Another can cancel late and still be
charged. So only a _paid_ session becomes an income transaction; an attended one
nobody has settled is a debt, listed as such and never counted as income. That
is why the page reports what a month _earned_ apart from what it _received_: a
busy month can still leave you short, and one merged figure would hide exactly
that.

Debt gets a line of its own on the chart, and it is a _balance_ rather than a
monthly figure: what was still outstanding when each month closed. It rises when
an hour goes unpaid and falls when somebody settles, so its slope answers the
only question worth asking of it — is this getting better or worse. A running
total of unpaid work could only ever climb, and would look like a crisis in a
practice that was being paid perfectly well. It shares an axis with income
rather than getting a second one, so a few hundred owed can never be drawn as
tall as a few thousand earned.

The second is that an estimate is a range, not a number, and that the range
comes from counting appointments rather than from averaging months.

Next month is not a mystery. Clients have standing appointments, so the month is
a known list, and each entry on it either goes ahead or does not — a run of
independent yes/no trials. That makes both halves of the answer arithmetic
rather than guesswork: the middle is the sum of each fee times the chance that
appointment survives, and the spread is the binomial variance of the same list.
The strangers who have not rung up yet are added on top at the rate they have
historically arrived at, which is what a Poisson estimate is for. The band is
then 1.96 standard deviations either way, so the month lands inside it about
nineteen times in twenty.

The chance an appointment survives is measured per client, blended toward the
practice's own rate until that client has a record of their own, so one
cancellation cannot write somebody off. Concentration shows up honestly:
variance grows with the square of the fee, so one client worth four hundred a
month is a wider band than four worth a hundred each.

Clients also move on, and somebody leaving is not a cancellation — it takes every future
appointment with it. Archiving a client is what records one, so the rate at
which people move on is measured from the caseload itself. Each
month a client stays carries the same chance of being their last, which makes
the length of a course geometrically distributed and gives two figures a monthly
total never could: how long a client typically stays, and what one is therefore
worth over the whole of it.

That rate is then charged against every appointment by how far off it is. A
standing Monday appointment in the last week of next month is worth less than
the identical one this week, because they might stop coming in between, and the
hazard compounds across whole months rather than being applied in a lump — a
client's last session is not a session they missed. It is why the estimate for
next month sits below the one for this month on the same diary, and why its band
is wider.

This is the whole reason to count rather than average. An average of past months
describes the practice you had; counting appointments describes the roster you
have, so taking on a client moves the estimate that day instead of half a year
later. Averaging the last few months survives only as the fallback, for somebody
who keeps no schedules and books nothing ahead.

Both this month and next are estimated, and one rule covers them: work already
done is a fact, so it is added as a floor the range can never fall below, and
only the appointments still to come carry any uncertainty. For next month there
is no floor yet. For the month in progress it grows as the month fills up, so on
the 25th the estimate is mostly fact and the band has quietly closed around the
truth. The page says underneath how many appointments the figure counted and how
many it expects to happen, so it can always be checked against a diary.

Client names are the one piece of data here the server cannot read. They are
encrypted in the browser under a key wrapped by a PIN that never leaves the
device, so a copy of the database is a list of fees and dates with nobody
attached to it.

The PIN belongs to a person, not to the household, and that is the one place
this feature breaks the "everything below the household is shared" rule. A
practice belongs to whoever runs it. Everyone in the household sees the
sessions, the fees and the income, because that is household money and it lands
in the shared ledger; only the person who added a client can read that client's
name. To anybody else the row shows the figures with the name as dots, and no
PIN of theirs will ever open it. They also cannot edit or remove that client,
because saving from their screen would write over a name they cannot see.

The cost is real and worth stating: names cannot be searched or sorted on the
server, and a forgotten PIN loses that person's names for good — though every
fee, session and euro survives it. The transactions a paid session writes carry
a plain label, "Session" by default, rather than a name, because writing the
name into the ledger would undo the whole arrangement.

Money is entered by hand. There is no bank sync and no split transactions:
leaving them out is what keeps the app small. Accounts and budgets are in the
household's one currency; investments are the exception, because a listing
quotes in whatever its exchange says and restating that would be a lie about
the market. Those are converted with the latest rate fetched, one per pair.

Market data is the one part of the app that depends on somebody else, so it is
built to be cheap and to fail quietly. Prices come from EODHD, which needs a
free key and is the one free plan checked that quotes European listings as well
as US ones. It bills one API call per holding rather than per request, and a
free plan allows twenty a day, so a fetched price is reused for two hours
(`MARKET_DATA_CACHE_HOURS`) before the provider is asked again. Exchange rates
come from Frankfurter instead, which is free and needs no key, so rates never
compete with prices for the same budget. When the provider cannot be reached,
the last price fetched stays on the row and the page says how old it is: the
figures go stale, never wrong and never absent. A price can also be typed in by
hand, for a day the allowance runs out or a listing the provider does not carry;
a typed price is used exactly like a fetched one and is labelled as typed, so
the two are never confused. The rates behind every converted figure are listed
on the page rather than left implicit. A trade can name the account it was
bought through, and then it moves the cash: a buy takes it out of that
brokerage account and a sell puts it back, exactly as a broker's statement
shows. Getting money to the broker in the first place is an ordinary transfer
from a bank account, recorded like any other, so the brokerage balance can hold
cash between trades. Net worth adds the accounts and the holdings together and
counts nothing twice: a euro is either still cash or already a holding.

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

| Command                 | What it does                                                        |
| ----------------------- | ------------------------------------------------------------------- |
| `make dev`              | Build and start everything, reloading on changes                    |
| `make stop`             | Stop the stack                                                      |
| `make clean`            | Stop the stack and remove containers, networks, volumes, and images |
| `make logs`             | Follow the backend logs                                             |
| `make logs-web`         | Follow the frontend logs                                            |
| `make format`           | Format the Python code                                              |
| `make lint`             | Check types and lint the Python code                                |
| `make test-unit`        | Run the unit tests and show coverage                                |
| `make test-integration` | Run the integration tests against a real Postgres                   |
| `make web`              | Run the web app on the host instead of in Docker                    |
| `make web-build`        | Type check and build the web app                                    |
| `make web-format`       | Format the frontend code                                            |
| `make web-lint`         | Type check and lint the frontend code                               |
| `make web-test-unit`    | Run the frontend unit tests                                         |
| `make web-api`          | Regenerate the API client from the backend's schema                 |
| `make web-api-check`    | Fail if the committed API client is out of date                     |

## Deploying to Railway

Three services, described in one file, [`.railway/railway.ts`](.railway/railway.ts).

| Service    | What it is                                                                                                               | Public?                           |
| ---------- | ------------------------------------------------------------------------------------------------------------------------ | --------------------------------- |
| `web`      | The compiled web app, served by Caddy, which also forwards `/api` and `/assets` to the backend over the private network. | Yes. This is the app's address.   |
| `backend`  | The FastAPI app.                                                                                                         | No. Reachable only through `web`. |
| `postgres` | Railway's managed Postgres.                                                                                              | No.                               |

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

CI regenerates the client on every pull request and fails if the result differs
from what is committed, so a forgotten `make web-api` cannot merge. It also type
checks the frontend against the client, which is what makes "the two cannot
drift" a check rather than a convention.

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
