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
