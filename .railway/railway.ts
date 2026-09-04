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
// Both services build from this repository, so a push to main redeploys them.
// No secret is written here: preserve() means "keep the value already set in
// Railway", so those are set once in the dashboard and stay out of git.

import { defineRailway, github, postgres, preserve, project, service } from 'railway/iac'

const REPO = 'dpoulopoulos/hydra'

// The web service is the only one with a public address, so it is the address
// of the whole app. Written as a reference rather than read from the `web`
// object below, because the two services point at each other and one of the
// two has to be named before it exists.
const PUBLIC_HOST = 'https://${{web.RAILWAY_PUBLIC_DOMAIN}}'

// The backend is told which port to listen on instead of being assigned one,
// so that the web service can name it in the address it forwards to.
const BACKEND_PORT = '8000'

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
    env: {
      // Private networking: this name resolves inside the project only, so the
      // API is never reachable from outside except through this service.
      // Written as a reference for the same reason PUBLIC_HOST is: a reference
      // is a value Railway resolves, so it cannot be pasted into a string here.
      BACKEND_ORIGIN: `http://\${{backend.RAILWAY_PRIVATE_DOMAIN}}:${BACKEND_PORT}`,
    },
  })

  return project('hydra', {
    resources: [db, backend, web],
  })
})
