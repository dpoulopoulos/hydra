# Development image for the web app.
#
# The compose stack runs Vite's dev server in here so the frontend starts
# alongside the backend and reloads on a change. Production packaging is not
# covered yet: `pnpm build` emits static files, and how they are served depends
# on where this is deployed.

FROM node:24-slim

WORKDIR /app

# pnpm comes from corepack, pinned by the packageManager field in package.json,
# so the container and a developer's machine use the same version.
RUN corepack enable

# Dependencies are installed in their own layer, so editing source does not
# reinstall them. node_modules stays inside the image: it is built for the
# container's platform and must not be replaced by the host's copy.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0, without which the port mapping would reach nothing.
CMD ["pnpm", "dev", "--host"]
