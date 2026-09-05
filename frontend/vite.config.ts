import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

// Set by the compose stack. Inside a container the dev server has to listen on
// every interface, and file changes arrive as writes from outside the process,
// which inotify does not always report through a bind mount or a synced path.
const inContainer = process.env.VITE_IN_CONTAINER === 'true'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), babel({ presets: [reactCompilerPreset()] }), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  // Unit tests run in jsdom against the same aliases and plugins as the app,
  // so a test imports a component exactly the way a screen does.
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    // The date helpers read the local calendar day, so without a fixed zone a
    // test asserting a date passes in London and fails in Auckland.
    env: { TZ: 'UTC' },
  },
  build: {
    // Vite calls this folder "assets" by default, but the API already serves
    // /assets: the logo the emails point at. In production both sit behind one
    // origin, so the built bundles are given a name of their own instead.
    assetsDir: 'static',
  },
  server: {
    port: 5173,
    // 0.0.0.0 in a container, so the published port reaches the server.
    host: inContainer ? true : undefined,
    watch: inContainer ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      // Talk to the backend on its own port in development, so the browser
      // sees one origin and CORS never enters the picture. The compose stack
      // points this at the backend service; override it with VITE_API_TARGET
      // when running outside containers on a non-standard port.
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
