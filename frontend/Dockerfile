# Two images from one file.
#
# The `dev` stage runs Vite's dev server, which is what the compose stack asks
# for by name. The last stage is the production one, and it is what a host
# building this folder gets by default: the app is compiled to static files and
# served by Caddy, which also forwards /api to the backend.

# --- shared dependency layer ------------------------------------------------

FROM node:24-slim AS deps

WORKDIR /app

# pnpm comes from corepack, pinned by the packageManager field in package.json,
# so the container and a developer's machine use the same version.
RUN corepack enable

# Dependencies are installed in their own layer, so editing source does not
# reinstall them. node_modules stays inside the image: it is built for the
# container's platform and must not be replaced by the host's copy.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# --- development ------------------------------------------------------------

FROM deps AS dev

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0, without which the port mapping would reach nothing.
CMD ["pnpm", "dev", "--host"]

# --- production build -------------------------------------------------------

FROM deps AS build

COPY . .

# Type checks and then emits the static files into dist.
RUN pnpm build

# --- production -------------------------------------------------------------

FROM caddy:2-alpine

# The Caddyfile serves /srv and proxies /api to the address in BACKEND_ORIGIN.
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

# A sensible value for running this image on its own. A host that puts the
# backend somewhere else overrides it.
ENV BACKEND_ORIGIN=http://backend:8000

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
