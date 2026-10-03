# scripts

Scripts for working on the whole app, rather than on one half of it.

## `seed.py`: demo data for a local instance

Fills a fresh local stack with demo data that touches every feature, so the
backend and the frontend can be tried without typing anything in first.

### Use it

```bash
make dev     # start the stack, if it is not running
make seed    # fill it
```

`make seed` runs `uv run scripts/seed.py`. The script declares its own
dependencies inline ([PEP 723](https://peps.python.org/pep-0723/)), so `uv`
fetches them on the first run and nothing needs installing.

When it finishes, it prints what you need to sign in and look around:

```
Done. Sign in at http://localhost:5173
  Owner:   admin@example.com (Clients PIN 123456)
  Partner: partner@example.com / demo-partner-password (Clients PIN 654321)
  Read/write API token for the MCP server: hyd_...
```

The owner's password is `FIRST_SUPERUSER_PASSWORD` from your `.env`.

### It needs an empty household

The script refuses a household that already has accounts, so it never doubles
up data or trips over names it created last time. To seed again, start from an
empty database:

```bash
make clean && make dev
make seed
```

### What it creates

Every date is relative to today, so the data looks current whenever it is
seeded. The random choices use a fixed seed, so two runs tell the same story.

| Feature      | What you get                                                                                                                     |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Household    | A name, a locale and a session label. A second member, and one invitation left pending.                                          |
| Accounts     | One of each type: current, savings, cash, credit card, brokerage. A sixth one, emptied and archived.                            |
| Categories   | A new parent with a child, a new child under a default parent, a new income category. One default archived.                     |
| Transactions | About six months of expenses, income and transfers, by both members. The card is paid off each month for the month before.      |
| Budgets      | Limits from three months back through next month, made with bulk set and copy. One category is over its limit this month.       |
| Goals        | Three goals on the savings account, filled by tagged monthly transfers: one on track, one behind, one reached.                  |
| Recurring    | Monthly, weekly and yearly rules: rent, salary, subscriptions, transfers. One paused, one ended, one blocked by its archived account. |
| Investments  | Five instruments, one with no trades. Buys and a sell through the brokerage account, and typed prices.                          |
| Clients      | Turned on for both members. A PIN for each member. Clients on every kind of schedule, one archived, one free intake. Sessions attended, missed, cancelled, paid, owed, waived and still ahead. |
| API tokens   | A read token, a read/write token, and a revoked one.                                                                             |
| Reports      | Nothing of their own: they read everything above.                                                                                |

### How it works, and why

**It goes through the HTTP API, not the database.** Every row passes the same
validation the web app's would. If a change to the API breaks the seed, the
next run says so, with the request and the reply.

**The second member joins the real way.** They sign up, verify their address
and accept an invitation. The tokens for those steps are mailed, so the script
reads them back out of the mail catcher. If the mail catcher is not reachable,
the script skips the second member and the pending invitation, and seeds the
rest.

**Client names are encrypted as the browser does it.** Argon2id stretches the
PIN, which wraps a random data key, which encrypts each name with AES-GCM. The
parameters match `frontend/src/lib/income-vault.ts`, so the printed PINs
unlock the names on the Clients page. If that file changes how it encrypts, this
script has to change with it.

**Prices are typed, not fetched.** The portfolio is valued without a market
data key. The script then asks for one refresh: the typed prices are fresh, so
it spends no EODHD calls and only fetches the USD rate from Frankfurter. With
no network, the US listings stay unvalued and the rest still works.

### Options

| Option            | Default                                 | What it is                                               |
| ----------------- | --------------------------------------- | -------------------------------------------------------- |
| `--api-url`       | `http://localhost:8000`, or `SEED_API_URL`   | Where the backend is.                                    |
| `--mail-url`      | `http://localhost:1080`, or `SEED_MAIL_URL`  | Where the mail catcher is.                               |
| `--email`         | `FIRST_SUPERUSER` from `.env`           | Whose household to fill.                                 |
| `--password`      | `FIRST_SUPERUSER_PASSWORD` from `.env`  | That user's password.                                    |
| `--partner-email` | `partner@example.com`                   | The second member. This address must not have an account yet. |

Pass options through `uv` directly, for example to fill another user's
household:

```bash
uv run scripts/seed.py --email someone@example.com --password their-password --partner-email partner2@example.com
```
