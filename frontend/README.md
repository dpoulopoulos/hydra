# Frontend

The web app for hydra: a personal finance manager for tracking spending, setting
monthly budgets, and seeing where the money went.

## Stack

| Piece           | Choice                                                                    |
| --------------- | ------------------------------------------------------------------------- |
| Build           | Vite 8, React 19 with the React Compiler, TypeScript 6                    |
| Styling         | Tailwind CSS v4 with shadcn/ui (`radix-nova`)                             |
| Data            | TanStack Query, over a client generated from the backend's OpenAPI schema |
| Forms           | React Hook Form with Zod                                                  |
| Charts          | Recharts, via shadcn's chart wrapper                                      |
| Package manager | pnpm                                                                      |

## Getting started

The usual way is the whole stack, from the repository root:

```bash
make dev            # API, web app, Postgres, mail catcher
```

That runs this app in a container on http://localhost:5173, watching `src` and
reloading in place. Editing `package.json` or `pnpm-lock.yaml` rebuilds the
image instead, since dependencies cannot be swapped inside a running install.

For frontend-only work it is quicker on the host, which needs a backend running
somewhere:

```bash
pnpm install
pnpm dev            # http://localhost:5173
```

If that backend is not on port 8000, point the proxy at it:

```bash
VITE_API_TARGET=http://localhost:8001 pnpm dev
```

`make web` from the root does the same.

## Scripts

```bash
pnpm dev            # Dev server
pnpm build          # Type check, then build
pnpm typecheck      # Type check only
pnpm lint           # eslint
pnpm format         # prettier
pnpm generate:api   # Re-dump the backend schema and regenerate src/api
```

## The generated API client

`src/api` is **generated** from the backend's own OpenAPI schema by
`@hey-api/openapi-ts`. Every request and response is typed from the source of
truth rather than restated by hand, and all 62 endpoints are covered.

Do not edit anything under `src/api`. After changing the API, run:

```bash
pnpm generate:api
```

That re-dumps the schema to `openapi.json` and regenerates the client. The
operation names read well (`householdsGetHouseholdMe`,
`transactionsListTransactions`) because the backend sets
`generate_unique_id_function` from each route's tag and name.

`src/api` is excluded from eslint and prettier, since it is not written by hand.

## Structure

```
src/
├── api/              # Generated. Do not edit.
├── components/
│   ├── ui/           # Vendored from shadcn/ui. `shadcn add` overwrites these.
│   ├── charts/       # Recharts wrappers, one per report
│   ├── layout/       # Shell, sidebar, headers
│   └── <feature>/    # Dialogs and pieces belonging to one page
├── hooks/            # Shared queries (household, accounts, categories) and useAuth
├── lib/              # Money, months, amounts, the chart palette, API config
├── pages/            # One module per route, each exporting `Component`
└── routes.tsx        # Public, open and in-app route arrays
```

## Three conventions worth knowing

**Money is never divided by 100 inline.** The API speaks integer minor units
throughout, and how many minor units make a major one is a property of the
currency, not a constant. `lib/money.ts` asks `Intl` for it, so a household in
a zero-decimal currency would format correctly with no special case.
`lib/amount.ts` converts the other way for form fields, accepting both `.` and
`,` as the decimal separator.

**Colour carries meaning in exactly two places.** `--positive` for money in and
`--negative` for money out. Everything else is the violet accent or neutral ink.
A transfer is neither spending nor income, so it is shown plain.

**The chart palette was computed, not chosen.** Seven slots, validated against
both surfaces for lightness, chroma, separation under simulated colour
blindness, and contrast. Colour follows the category rather than its rank, so
re-sorting a chart never repaints it, and an eighth series folds into a neutral
"Other" rather than getting a made-up hue.

## Pages

Sixteen routes cover the whole API.

| Route                                 | What it does                                             |
| ------------------------------------- | -------------------------------------------------------- |
| `/login`, `/signup`                   | Sign in; sign up, optionally from an invitation link     |
| `/forgot-password`, `/reset-password` | Request and use a reset link                             |
| `/verify-email`                       | Verify on arrival, or ask for a fresh link               |
| `/join-household`                     | Preview and accept an invitation                         |
| `/`                                   | Dashboard: the month's figures, budgets, latest activity |
| `/transactions`                       | The ledger, with the full filter set                     |
| `/accounts`                           | Accounts and balances                                    |
| `/categories`                         | The two-level category tree                              |
| `/budgets`                            | Monthly limits, per category or a month at a time        |
| `/recurring`                          | Recurring rules and what is still to come                |
| `/reports`                            | The four charts, with a table view                       |
| `/settings/household`                 | Household, members, invitations                          |
| `/settings/profile`                   | Your details, password, account deletion                 |
| `/settings/users`                     | Every account, for a superuser                           |

## Running in the container

`Dockerfile` builds two images from one file.

The `dev` stage runs Vite's dev server, and the compose file asks for it by
name. The last stage is the production one, and it is what anything building
this folder gets by default: `pnpm build` compiles the app, and Caddy serves the
result, forwarding `/api` and `/assets` to the address in `BACKEND_ORIGIN`.
See `Caddyfile`.

The browser therefore sees one origin in production too, exactly as it does
behind the dev server's proxy, which is why the generated client sends relative
URLs and no CORS is involved. Vite's own bundles are written to `static/` rather
than the usual `assets/`, because `/assets` already belongs to the API: it is
where the logo in the emails is served from.

Two things differ inside a container, both switched on by `VITE_IN_CONTAINER`
in the compose file:

- the dev server binds `0.0.0.0`, without which the published port would reach
  nothing;
- the file watcher polls, because writes arriving from outside the container are
  not reliably reported by inotify.

`node_modules` is never synced from the host. It is built for the container's
platform, and `.dockerignore` keeps the host's copy out of the image.

## Notes on the vendored parts

Components under `src/components/ui` come from shadcn/ui, and `shadcn add`
overwrites them. Two eslint rules are switched off for that directory because
its house patterns trip them: exporting a `cva` variants object beside a
component, and priming state from a media query inside an effect. Fixing them
in place would be undone by the next update.

The React Compiler declines to compile the components that use React Hook Form,
which it treats as an incompatible library. Those appear as
`Compilation Skipped` warnings and mean those components are not automatically
memoised. They are not defects.
