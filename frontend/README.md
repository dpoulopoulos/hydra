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
pnpm test           # Unit tests, once
pnpm test:watch     # Unit tests, on every change
pnpm generate:api   # Re-dump the backend schema and regenerate src/api
```

## Tests

Vitest, in jsdom, sharing this app's Vite config, so a test imports a module
exactly the way a screen does. `make web-test-unit` from the repository root
runs the same command, and so does CI on every pull request. Neither a backend
nor Docker is needed.

A test lives beside the module it covers, as `<module>.test.ts`, so `pnpm test`
picks it up from anywhere under `src`. Components and pages render through
Testing Library; the pure modules under `src/lib` are tested as tables, which
is where the money and date logic lives: the amounts a form accepts, the
minor-unit conversions across a two-, a zero- and a three-decimal currency, the
month arithmetic around a year end and a leap February, the query the
transaction filters serialise to, and the password rules. A wrong colour is
obvious; a wrong amount is not.

Two of those tables pin behaviour that is wrong today rather than pretending it
is right: a thousands separator read as a decimal point ([#18][i18]) and a
timestamp truncated to its UTC date ([#36][i36]). Each is marked as such and
has to be flipped by the change that fixes it.

Those helpers hand `Intl` no locale and no time zone, so what a test sees
otherwise depends on the machine it runs on: `€42.50` here is `42,50 €` on a
German laptop. `src/test/setup.ts` pins the fallback locale for the whole
suite, and `vite.config.ts` pins the zone, so an assertion means the same thing
on a laptop as it does in CI. A caller that asks for a locale of its own still
gets it.

[i18]: https://github.com/dpoulopoulos/hydra/issues/18
[i36]: https://github.com/dpoulopoulos/hydra/issues/36

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
`lib/amount.ts` converts the other way for form fields, deciding what each
separator in a typed amount _is_ — so "1,200" is twelve hundred to an en-US
reader and "1.200" is the same figure to a de-DE one — rather than assuming.

Because the parser reads the reader's separators, a field holding a saved
amount must be filled with `formatMajorInput`, never `String(toMajor(...))`.
A bare `String` always writes a dot, and in a locale that groups with one a
three-decimal amount would read back a thousand times too big.

**Colour carries meaning in exactly two places.** `--positive` for money in and
`--negative` for money out. Everything else is the violet accent or neutral ink.
A transfer is neither spending nor income, so it is shown plain.

**The chart palette was computed, not chosen.** Seven slots, validated against
both surfaces for lightness, chroma, separation under simulated colour
blindness, and contrast. Colour follows the category rather than its rank, so
re-sorting a chart never repaints it, and an eighth series folds into a neutral
"Other" rather than getting a made-up hue.

## Pages

Eighteen routes cover the whole API.

| Route                                 | What it does                                                             |
| ------------------------------------- | ------------------------------------------------------------------------ |
| `/login`, `/signup`                   | Sign in; sign up, optionally from an invitation link                     |
| `/forgot-password`, `/reset-password` | Request and use a reset link                                             |
| `/verify-email`                       | Verify on arrival, or ask for a fresh link                               |
| `/join-household`                     | Preview and accept an invitation                                         |
| `/`                                   | Dashboard: the month's figures, budgets, latest activity                 |
| `/transactions`                       | The ledger, with the full filter set                                     |
| `/accounts`                           | Accounts and balances                                                    |
| `/investments`                        | Holdings, their value, and the trades behind them                        |
| `/income`                             | Clients, sessions, what is owed, and where this month and next will land |
| `/categories`                         | The two-level category tree                                              |
| `/budgets`                            | Monthly limits, per category or a month at a time                        |
| `/recurring`                          | Recurring rules and what is still to come                                |
| `/reports`                            | The four charts, with a table view                                       |
| `/settings/household`                 | Household, members, invitations                                          |
| `/settings/profile`                   | Your details, password, account deletion                                 |
| `/settings/users`                     | Every account, for a superuser                                           |

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

Neither image runs as root. The dev stage drops to the `node` user (uid 1000)
that `node:24-slim` already ships, before dependencies are installed, so the
install tree, Vite's cache and pnpm's store all belong to it; the production
stage drops to an `app` user of its own. If something in the dev container ever
needs to write a path it does not own, give that path to `node` in the
`Dockerfile` rather than taking the `USER` line out.

`make web-test-dev` from the repository root builds the dev image and checks
that it runs unprivileged and still serves a synced file. It needs Docker.

## Security headers in production

The session token is kept in `localStorage`, so any script running on the origin
can read it. What keeps a script that should not be there from running at all is
the browser, told what to allow by the response headers `Caddyfile` sets:

| Header                      | Value                                                         |
| --------------------------- | ------------------------------------------------------------- |
| `Content-Security-Policy`   | `'self'` throughout, plus `data:` images and style attributes |
| `X-Content-Type-Options`    | `nosniff`                                                     |
| `Referrer-Policy`           | `no-referrer`                                                 |
| `X-Frame-Options`           | `DENY`                                                        |
| `Strict-Transport-Security` | one year, including subdomains                                |

Two of those are worth a word. The policy is nearly all `'self'` because there is
one origin to allow: the bundles and fonts under `/static`, and the API under
`/api`. Styles are the exception, and only half of one: `style-src-attr` allows
inline styles, because the UI components set style attributes with values they
compute as they render, while `style-src-elem` allows no stylesheet the page did
not come with. And `no-referrer` matters here in particular, since password
reset, email verification and invite links all carry a single use token in the
query string, which a `Referer` header would otherwise hand to whatever other
origin the page happens to talk to.

Radix and next-themes do build a stylesheet while they run, for the scroll lock
behind a dialog and for suppressing transitions across a theme change. Caddy
renders a fresh nonce into the entry page and names the same value in the
header of every response, and `src/lib/csp-nonce.ts` hands it to them on start
up, so those stylesheets are taken and later ones are not. Two more things stay
off that path entirely: shadcn's chart wrapper, which sets its colours on the
container's style attribute instead of emitting a stylesheet, and sonner, whose
stylesheet is imported from `sonner/dist/styles.css` and bundled rather than
injected. See `withoutSonnerStyleInjection` in `vite.config.ts`.

A new front end dependency that loads something from elsewhere will be blocked,
and will say so in the browser console. Widen the policy deliberately when that
happens, rather than by reflex.

`make web-test` from the repository root runs the `Caddyfile` in a container and
checks the headers and the routing. It needs Docker, but not a build of the app.

## Notes on the vendored parts

Components under `src/components/ui` come from shadcn/ui, and `shadcn add`
overwrites them. `chart.tsx` is the one that has been changed on purpose:
upstream renders the series colours as a `<style>` element, which the production
policy refuses, so it sets them as custom properties on the container instead.
`chart.test.tsx` fails if an update puts the stylesheet back. Two eslint rules are switched off for that directory because
its house patterns trip them: exporting a `cva` variants object beside a
component, and priming state from a media query inside an effect. Fixing them
in place would be undone by the next update.

## Notes on the forms

The React Compiler treats React Hook Form's `watch()` as an incompatible
library: it returns a function that cannot be memoised safely, and rather than
risk a stale UI the compiler skips the whole component. Watch fields with
`useWatch({ control, name })` instead, which subscribes through the control and
leaves nothing for the compiler to object to.

A form that fills itself in from an effect has to go through `refill()` from
`src/lib/form.ts` rather than call `reset()` itself. A plain `reset()` empties
the field map and counts on the next render calling `register()` again, which a
memoised render need never repeat: the fields stay unregistered and the form
hands the mutation nothing, however full the dialog looks. `refill()` keeps the
registrations and writes each value onto the field itself, so it does not
matter how few times the form renders, or how often it is called. The one
exception is a field that must not overwrite what is being typed, such as the
household rename: that resets with `{ keepFieldsRef: true, keepDirtyValues: true }`.

Nothing about this is enforced by types, so `src/test/react-compiler.test.ts`
compiles the source the way the build does and fails on a component the compiler
had to skip. The compiler runs over the tests too: its preset limits itself to
the client environment, which Vitest is not, so `vite.config.ts` widens it and
the tests render the same memoised components the browser does.
