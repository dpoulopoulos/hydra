import { defineConfig } from '@hey-api/openapi-ts'

// The client is generated from the backend's own schema, so every endpoint and
// payload is typed from the source of truth rather than restated by hand.
// Regenerate with `pnpm generate:api` after changing the API.
export default defineConfig({
  input: './openapi.json',
  output: {
    path: './src/api',
    format: 'prettier',
    lint: false,
  },
  plugins: [
    { name: '@hey-api/client-fetch', bundle: true },
    { name: '@hey-api/typescript', enums: 'javascript' },
    { name: '@hey-api/sdk', asClass: false },
    { name: '@tanstack/react-query' },
  ],
})
