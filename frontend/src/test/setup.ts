import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Vitest runs without globals, so Testing Library cannot register its own
// automatic cleanup. Unmount between tests here instead, or a test would find
// the previous test's DOM still on screen.
afterEach(() => {
  cleanup()
})

// jsdom implements no layout, so it ships no ResizeObserver. Radix reads
// element sizes through one in several of the primitives the app builds on, so
// a component test would crash on mount without a stand-in.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Radix drives its select with pointer capture and scrolls the chosen option
// into view. jsdom implements neither, so opening a picker in a test would
// throw before the options were ever on screen.
Element.prototype.hasPointerCapture ??= () => false
Element.prototype.setPointerCapture ??= () => {}
Element.prototype.releasePointerCapture ??= () => {}
Element.prototype.scrollIntoView ??= () => {}

// Intl falls back to the machine's locale when none is given, and the money and
// date helpers never give one, so "€42.50" here is "42,50 €" on a German laptop
// — in these tests and in the component tests that render through the same
// helpers. Pin the fallback for the whole suite, so a formatting assertion
// means the same thing everywhere it runs; a caller that passes a locale still
// wins over it. The time zone is pinned alongside it, in vite.config.ts.
function withDefaultLocale<T extends typeof Intl.NumberFormat | typeof Intl.DateTimeFormat>(
  Format: T,
): T {
  return new Proxy(Format, {
    construct: (target, [locales, options]: [Intl.LocalesArgument, object?]) =>
      new (target as new (l: Intl.LocalesArgument, o?: object) => object)(
        locales ?? 'en-US',
        options,
      ),
    apply: (target, _thisArg, [locales, options]: [Intl.LocalesArgument, object?]) =>
      (target as (l: Intl.LocalesArgument, o?: object) => object)(locales ?? 'en-US', options),
  })
}

Intl.NumberFormat = withDefaultLocale(Intl.NumberFormat)
Intl.DateTimeFormat = withDefaultLocale(Intl.DateTimeFormat)
