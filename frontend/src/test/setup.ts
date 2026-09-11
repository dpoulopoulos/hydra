import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import { pinLocale } from '@/test/locale'

// The suite reads money, quantities and dates as they appear on screen, and
// the app formats all three without naming a locale, so the machine's own
// locale decides what "EUR 1,200.50" looks like. Pin the fallback for every
// file, or a run on a machine set to de-DE fails on formatting alone. A caller
// that names a locale still wins over it, and a file about a particular locale
// can call `pinLocale` with its own. The time zone is pinned alongside it, in
// vite.config.ts.
pinLocale('en-US')

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
