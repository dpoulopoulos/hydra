// The whole Railway project, in one file.
//
// The CLI compares this with the live environment and shows you the difference
// before it changes anything:
//
//   npm install                 # once, to fetch the railway package
//   railway login && railway link
//   railway config plan         # read only: what would change
//   railway config apply        # do it, after you confirm
//
// Every service builds from this repository, so a push to main redeploys them.
// No secret is written here: preserve() means "keep the value already set in
// Railway", so those are set once in the dashboard and stay out of git.

import { defineRailway, github, postgres, preserve, project, service } from 'railway/iac'

const REPO = 'dpoulopoulos/hydra'

// The app's public address. The backend reads it for the links and the logo in
// its emails, so it has to be the address people actually visit.
//
// This was ${{web.RAILWAY_PUBLIC_DOMAIN}}, which reads the domain rather than
// repeating it. That reference is resolved when the backend deploys, and it
// went stale and stayed stale when the domain changed, leaving every link in
// every email pointing at an address that no longer answered. A literal cannot
// drift out of step with what the emails say.
const PUBLIC_DOMAIN = 'hydra.dimpo.dev'
const PUBLIC_HOST = `https://${PUBLIC_DOMAIN}`

// Each service is told which port to listen on rather than being assigned one.
// The backend's is named by the web service in the address it forwards to. The
// web service's is the port Caddy binds, and a generated domain does not
// always pick one up on its own: check it with `railway domain list`.
const BACKEND_PORT = '8000'
const WEB_PORT = '8080'
const MCP_PORT = '8002'

// The MCP server needs its own public address: a client connects to it
// directly, and it is not behind the web service's proxy. Everything it
// serves is gated on a hydra API token, which is the only thing standing
// between that address and somebody's finances.
const MCP_DOMAIN = 'mcp.hydra.dimpo.dev'

export default defineRailway((ctx) => {
  const db = postgres('postgres')

  const backend = service('backend', {
    source: github(REPO, { rootDirectory: 'backend' }),
    healthcheck: '/health',
    // The migrations and the seed data run once per deploy, here, rather than
    // once per container from the entrypoint.
    preDeploy: 'bash /app/scripts/prestart.sh',
    env: {
      ENVIRONMENT: ctx.isEnvironment('production') ? 'production' : 'staging',
      PORT: BACKEND_PORT,
      RUN_PRESTART: 'false',

      PROJECT_NAME: 'hydra',
      PROJECT_ID: 'Hydra',

      POSTGRES_SERVER: db.env.PGHOST,
      POSTGRES_PORT: db.env.PGPORT,
      POSTGRES_USER: db.env.PGUSER,
      POSTGRES_PASSWORD: db.env.PGPASSWORD,
      POSTGRES_DB: db.env.PGDATABASE,

      // Both are the web app's address: the links in the emails open the app,
      // and the logo in them is served back through the same proxy.
      FRONTEND_HOST: PUBLIC_HOST,
      BACKEND_HOST: PUBLIC_HOST,
      // One origin, so there is no cross-site request left to allow.
      BACKEND_CORS_ORIGINS: '',

      // Outgoing SMTP is blocked below Railway's Pro plan, so mail leaves over
      // HTTPS instead.
      EMAIL_PROVIDER: 'resend',
      EMAILS_FROM_NAME: 'hydra',

      // Set these in the Railway dashboard. Changing SECRET_KEY signs
      // everyone out.
      SECRET_KEY: preserve(),
      FIRST_SUPERUSER: preserve(),
      FIRST_SUPERUSER_PASSWORD: preserve(),
      RESEND_API_KEY: preserve(),
      EMAILS_FROM_EMAIL: preserve(),
    },
  })

  const web = service('web', {
    source: github(REPO, { rootDirectory: 'frontend' }),
    healthcheck: '/',
    // The generated *.up.railway.app domain stays too, and is not written here:
    // Railway does not put its own generated domains in this file.
    domains: [{ domain: PUBLIC_DOMAIN, port: Number(WEB_PORT) }],
    env: {
      PORT: WEB_PORT,
      // Private networking: this name resolves inside the project only, so the
      // API is never reachable from outside except through this service.
      //
      // Left as a reference, unlike PUBLIC_HOST, because a private domain is
      // derived from the service name and so cannot go stale under you. It is
      // written out rather than read from `backend.env`, because the two
      // services point at each other and one has to be named before it
      // exists.
      BACKEND_ORIGIN: `http://\${{backend.RAILWAY_PRIVATE_DOMAIN}}:${BACKEND_PORT}`,
    },
  })

  const mcp = service('mcp', {
    source: github(REPO, { rootDirectory: 'mcp-server' }),
    healthcheck: '/health',
    // Describing a domain here keeps it from being removed; it does not
    // create one. Railway's configuration cannot register a custom domain,
    // and a domain cannot be registered against a service that does not exist
    // yet, so a new service is a three step job: apply this file to create it,
    // add the domain to it in the dashboard, then write the domain here.
    domains: [{ domain: MCP_DOMAIN, port: Number(MCP_PORT) }],
    env: {
      // Both, and the same number. MCP_PORT is what the server binds; PORT is
      // how Railway knows where to send traffic and where to run the health
      // check. Setting only the first leaves the container listening and
      // Railway knocking on a door nobody is behind.
      MCP_PORT,
      PORT: MCP_PORT,
      // Private networking, for the same reason the web service uses it: the
      // agent's traffic reaches the API inside the project rather than going
      // out to the internet and back through Caddy.
      HYDRA_API_BASE_URL: `http://\${{backend.RAILWAY_PRIVATE_DOMAIN}}:${BACKEND_PORT}`,
      // What a client connects to, which is this service's own public address.
      MCP_RESOURCE_URL: `https://${MCP_DOMAIN}/mcp`,

      // No credential is set here, and the server reads none: each client
      // sends its own. A token on the service would make the whole deployment
      // act as one person, whoever connected.
    },
  })

  return project('hydra', {
    resources: [db, backend, web, mcp],
  })
})
