# Deploying hydra to Railway

A first deployment, start to finish. Every step is a command you can copy, and each one says what it does and how to
tell it worked.

The project is described in [`.railway/railway.ts`](.railway/railway.ts). The Railway CLI reads that file, compares it
with your live project, and shows you the difference before it changes anything.

## What you end up with

```
                    ┌──────────────────────────────┐
  browser ─────────►│  web        (public domain)  │
                    │  Caddy serves the built app  │
                    └───────────┬──────────────────┘
                                │  /api  /assets
                                │  private network
                    ┌───────────▼──────────────────┐
  AI agent ────┐    │  backend    (no public URL)  │
               │    │  FastAPI                     │
               │    └───────────┬──────────────────┘
               │                │  private network
  ┌────────────▼─────────────┐  │
  │  mcp   (public domain)   │──┘
  │  tools over the API      │     private network
  └──────────────────────────┘  ┌──────────────────┐
                                │  postgres        │
                                └──────────────────┘
```

| Service    | What it is                                                                                  | Public                          |
| ---------- | ------------------------------------------------------------------------------------------- | ------------------------------- |
| `web`      | The compiled app, served by Caddy, which also forwards `/api` and `/assets` to the backend. | Yes. This is the app's address. |
| `mcp`      | The MCP server, which gives an AI agent tools over the API.                                 | Yes, on its own domain.         |
| `backend`  | The FastAPI app.                                                                            | No.                             |
| `postgres` | Railway's managed Postgres.                                                                 | No.                             |

The browser only ever talks to one origin, so it never makes a cross-site request. That is why there is no CORS
configuration to get wrong, and why the API is not reachable except through the web service.

The MCP server is the one other thing with a public address, because a client connects to it directly rather than
through the app. It reaches the API over the private network like the web service does, and it holds no credential of
its own: every request carries the caller's own hydra API token, minted in the app under Settings, and hydra decides
from that token which household the request can reach. One deployment therefore serves everybody, each seeing only
their own. See [mcp-server/README.md](mcp-server/README.md).

## Before you start

- A [Railway](https://railway.com) account, with your GitHub account connected to it, and the Railway app installed on
  this **private** repository. Install it at
  [github.com/apps/railway-app/installations/new](https://github.com/apps/railway-app/installations/new) and grant it
  `hydra` by name, or every repository. Do this before step 4: `railway config apply` writes down the repository it was
  told to use without checking that it can read it, so a missing grant leaves you with services that never build and a
  plan that reports no drift.
- A [Resend](https://resend.com) account, with a sending domain verified. You need one API key and one from-address.
  Read [why not SMTP](#why-email-goes-over-https-and-not-smtp) if you are wondering.
- Node.js, to fetch the one package `.railway/railway.ts` imports.
- Your work committed and pushed to `main`. Railway builds from the repository, not from your working copy, so anything
  uncommitted will not be deployed.

## Step 1 — install the CLI and log in

The engine that reads `.railway/railway.ts` ships inside the CLI, so it has to be version **5.42.1 or newer**.

```bash
brew install railway          # or: npm i -g @railway/cli
railway --version             # must be >= 5.42.1
railway login
```

`railway login` opens a browser. On a machine without one, use `railway login --browserless`.

## Step 2 — fetch the SDK

`.railway/railway.ts` imports `railway/iac`, which comes from a package at the repository root. Install it once:

```bash
cd /path/to/hydra
npm install
```

## Step 3 — create an empty project and link it

```bash
railway init --name hydra
```

This makes the project and links this directory to it. Every command below then knows which project you mean.

Already have a Railway project you want to use instead? Run `railway link` and pick it from the list.

## Step 4 — create the four services

Read the plan first. It is the list of changes, and nothing happens until you confirm it:

```bash
railway config plan
```

You should see four additions: `postgres`, `backend`, `web`, and `mcp`. Then apply:

```bash
railway config apply
```

**The `backend` and `mcp` services fail to start at this point, and that is expected.** The backend has no configuration yet: no address to
put in its email links, and none of its secrets, and the MCP server has no backend to talk to. The next three steps
are what give them those.

## Step 5 — give the web service a domain

```bash
railway domain --service web
```

```
Service domain created:
  URL: https://web-production-20157.up.railway.app
  ID: 97a316ed-2f3b-4c54-bd29-e8aa123ac334
  Type: service
  Target port: -
  Sync status: CREATING
  Created: 2026-09-04T12:34:37.795+00:00
  Updated: 2026-09-04T12:34:37.795+00:00
```

That address is the app's address. The backend reads it too, for the links and the logo in its emails, so it has to
exist before the backend can start.

Write it down. You need it in step 8.

Whichever domain you use, check that it has a target port:

```bash
railway domain list --service web
```

A generated domain can arrive without one, and then the edge has nowhere to send traffic: every path answers 404 with an
`x-railway-fallback: true` header, while the container itself is healthy and passing Railway's own health check. Set it
with `railway domain update <domain> --service web --port 8080`.

Using your own domain instead? Add it to the `domains` list in `.railway/railway.ts`, apply, and then create **both**
records Railway prints: the `CNAME`, and the `_railway-verify` `TXT`. With only the `CNAME` the name resolves and every
request still answers 404, because Railway will not route traffic until the `TXT` has proved you own the domain.

## Step 6 — set the secrets

These five live only in Railway. `.railway/railway.ts` lists them as `preserve()`, which means "whatever is already
set", so no secret is ever written into git.

```bash
railway variable set --service backend \
  FIRST_SUPERUSER='you@example.com' \
  FIRST_SUPERUSER_PASSWORD='pick-something-long' \
  RESEND_API_KEY='re_...' \
  EMAILS_FROM_EMAIL='noreply@your-verified-domain.com'

# Read from stdin, so the key never lands in your shell history.
openssl rand -hex 32 | railway variable set --service backend SECRET_KEY --stdin
```

| Variable | What it is |
|---|---|
| `SECRET_KEY` | Signs the session tokens. The app refuses to start without it, or on an empty one. Changing it later signs everyone out. |
| `FIRST_SUPERUSER` | The address you will sign in with. |
| `FIRST_SUPERUSER_PASSWORD` | Its password. The app refuses to start on an empty one. |
| `RESEND_API_KEY` | An API key from Resend. |
| `EMAILS_FROM_EMAIL` | An address on a domain Resend has verified for you. |

Check they are all there:

```bash
railway variable list --service backend
```

## Step 7 — deploy for real

Setting a variable already triggers a deploy, so the backend is probably coming up on its own. If it is not, or you want
to be sure both services are running the current configuration:

```bash
railway redeploy --service backend --yes
railway redeploy --service web --yes
```

Watch the backend come up:

```bash
railway logs --service backend --latest
```

`--latest` follows the newest deployment even while it is building or if it fails, which is exactly the one you want to
read here.

You are looking for the migrations running, the first user being created, and then `Application startup complete`.

## Step 8 — check it

Use the domain from step 5.

```bash
D=https://YOUR-DOMAIN
for p in / /budgets /assets/logo.svg /api/v1/openapi.json; do
  printf '%-24s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' $D$p)"
done
```

All four answer `200`, and each one proves a different thing: the app is served, a path that only exists inside the app
is served too, the logo the emails point at comes back through the proxy, and the API is reachable behind it.

Do not check `/health` here. The backend has one, and Railway uses it, but Caddy forwards only `/api` and `/assets`, so
from outside that path is just another route of the app and answers with its HTML.

Then open `https://YOUR-DOMAIN` and sign in with the `FIRST_SUPERUSER` address and password from step 6.

## Step 9 — connect an AI agent (optional)

Skip this if you do not want one. Nothing else depends on it.

The `mcp` service carries its own domain, written in `.railway/railway.ts` as `MCP_DOMAIN`. Change it to one you own
before you apply, and create both records Railway prints, the `CNAME` and the `_railway-verify` `TXT`, exactly as for
the web domain in step 5. Check it answers:

```bash
curl -s https://YOUR-MCP-DOMAIN/health
```

`{"status":"ok"}`. That route is deliberately open: it is for Railway's health check, and it says nothing about
anybody's money.

Everything else needs a token. Mint one in the app, under **Settings → API tokens**, and copy it when it is shown:
that is the only time it appears. **Access** on that form decides what the agent gets: read only answers questions,
read and write also lets it record and delete transactions and set budgets. Then point a client at the server:

```bash
claude mcp add --transport http hydra https://YOUR-MCP-DOMAIN/mcp \
  --header "Authorization: Bearer hyd_..."
claude mcp list
```

Two things worth understanding before you leave this running.

The endpoint is on the public internet, and a hydra API token is the only thing between it and a household's
finances. That is the design: it is what lets one deployment serve everybody, each client sending its own token and
hydra deciding what that token reaches. It is also why a leaked token matters, and why tokens are revocable from the
same settings page. Mint read-only ones unless you actually want an agent recording transactions.

The server holds no credential of its own, and there is nowhere to put one. That is deliberate: a token configured
on the service would make the whole deployment act as one person, and every client that connected would read that
household, whoever they were.

Last, prove the email works: sign out, use **Forgot password**, and check that the message arrives. That exercises
Resend, the from-address, and the links, which are the three things most likely to be misconfigured.

---

## Day to day

### Deploying a change

**Push to `main`.** Both services build from the repository, so a push deploys them. Nothing else to run.

### Changing the infrastructure

Editing `.railway/railway.ts` is the one exception: a push does not read that file. After editing it:

```bash
railway config plan       # read this
railway config apply
```

`plan` is read-only and safe to run whenever you want to know whether Railway and the file have drifted apart.

### Stop each half rebuilding on the other's changes

By default a push to anything rebuilds both services. In each service's settings, find **Watch Paths** and set:

| Service | Pattern |
|---|---|
| `backend` | `/backend/**` |
| `web` | `/frontend/**` |

Patterns are measured from the repository root, not from the service's root directory.

### Logs and state

```bash
railway logs --service backend
railway logs --service web
railway status
```

### Rolling back

Open the service in the dashboard, find the last deployment that worked, and use **Redeploy** on it. This is faster than
reverting a commit and waiting for a build.

### Optional: wait for CI before deploying

Railway can hold a deployment until GitHub Actions passes. Turn on **Wait for CI** in each service's settings.

One catch: the workflows in `.github/workflows/` currently run on `pull_request` only. Wait-for-CI needs a workflow that
runs on `push`, so you would have to add that trigger first.

---

## Why email goes over HTTPS and not SMTP

**Railway blocks outgoing SMTP below its Pro plan.** So the deployed app does not use SMTP at all.
`EMAIL_PROVIDER=resend`, set in `.railway/railway.ts`, makes it post to the Resend API over HTTPS instead.

Nothing changes locally. There the setting stays `smtp`, and mail lands in the mail catcher at http://localhost:1080 as
it always did.

On the Pro plan you could use SMTP if you preferred: set `EMAIL_PROVIDER=smtp` and the `SMTP_*` variables, and redeploy.
Resend is still the better choice, for the delivery reporting alone.

## Troubleshooting

**`railway config plan` says the CLI is too old.** The IaC engine lives in the CLI now, not in the npm package. `brew
upgrade railway`, and check `railway --version` reads 5.42.1 or higher.

**`railway config plan` refuses because a service is managed by `railway.json`.** Nothing in this repository uses the
old per-service config, so this only happens on a project that predates it. Run `railway config migrate` and follow what
it prints.

**The backend keeps restarting.** Read `railway logs --service backend --latest`. Almost always a missing variable from
step 6: the app refuses to start on a half-configured environment rather than run in one. Confirm with `railway variable
list --service backend`.

**A build fails on the Dockerfile itself.** Railway's builder is stricter than the Docker on your machine, so an image
that builds locally can still be rejected before a line of it runs. It takes no mount but `type=cache`, and only with an
id carrying its own `s/<service id>-<path>` prefix, which cannot come from a variable. `backend/Dockerfile` therefore
uses no mounts at all, and says so; do not reintroduce one from a library's own Docker guide without checking it there
first.

**The site loads but every request fails.** The web service cannot reach the backend. Check that `BACKEND_ORIGIN` on
`web` resolves, and that `PORT` on `backend` is still `8000` — those two have to agree, and
[`.railway/railway.ts`](.railway/railway.ts) is what keeps them agreeing.

**The site loads but is unstyled, or blank.** A bundle is 404ing. The built files are served from `/static/`, not
`/assets/`, because `/assets` belongs to the API. If you have changed Vite's `build.assetsDir`, that is the cause.

**Emails never arrive.** In order: is the domain verified in Resend; does `EMAILS_FROM_EMAIL` use that domain; is
`RESEND_API_KEY` correct. Resend's own dashboard logs every attempt and its outcome, which is the quickest way to tell
whether the app sent anything at all.

**Links in the emails point at the wrong place.** `FRONTEND_HOST` and `BACKEND_HOST` on the backend are both built from
`PUBLIC_DOMAIN` in [`.railway/railway.ts`](.railway/railway.ts). Change the domain there, apply, and the backend
redeploys with it. It is written out rather than read from the web service on purpose: the reference that used to read
it went stale when the domain changed and stayed stale through a redeploy, which pointed every link in every email at
an address that no longer answered.
