import babel from '@rolldown/plugin-babel'
import tailwindcss from '@tailwindcss/vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig, type Plugin } from 'vitest/config'

// sonner ships its stylesheet inside its JavaScript and appends it to the head
// as a <style> element when the module is first imported. The production policy
// forbids that: `style-src-elem 'self'` honours no inline stylesheet, this one
// or an injected one (see Caddyfile), so the toasts would arrive unstyled.
//
// The same stylesheet is published as sonner/dist/styles.css, which main.tsx
// imports and the bundler folds into the app's own CSS file. This drops the
// injection, so the stylesheet is not also carried in the bundle and applied
// twice. It fails the build rather than the page if sonner stops injecting the
// same way, since the alternative is a policy violation nobody would see until
// production.
function withoutSonnerStyleInjection(): Plugin {
  const injector = 'function __insertCSS(code) {'

  return {
    name: 'sonner-without-style-injection',
    transform(code, id) {
      if (!id.includes('/sonner/dist/')) return null
      if (!code.includes(injector)) {
        if (!code.includes('__insertCSS')) return null
        this.error(
          'sonner injects its stylesheet in a way this plugin no longer recognises. ' +
            'Check how it does it now, and whether the app still needs to import ' +
            'sonner/dist/styles.css.',
        )
      }
      return { code: code.replace(injector, `${injector} return;`), map: null }
    },
  }
}

// Set by the compose stack. Inside a container the dev server has to listen on
// every interface, and file changes arrive as writes from outside the process,
// which inotify does not always report through a bind mount or a synced path.
const inContainer = process.env.VITE_IN_CONTAINER === 'true'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    tailwindcss(),
    withoutSonnerStyleInjection(),
  ],
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
