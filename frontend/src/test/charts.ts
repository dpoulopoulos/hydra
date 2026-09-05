import { fireEvent } from '@testing-library/react'

/**
 * Helpers for the chart tests.
 *
 * jsdom implements no layout, so recharts measures every container as 0x0 and
 * refuses to draw. These stand in for the parts of a browser a chart needs:
 * a size to draw into, and a way to reach a tooltip without a pointer.
 */

const BOX = { width: 640, height: 320, top: 0, left: 0, bottom: 320, right: 640, x: 0, y: 0 }

/** Give every element a fixed box, so a responsive chart has room to render. */
export function sizeCharts() {
  globalThis.ResizeObserver = class {
    callback: ResizeObserverCallback

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback
    }

    observe(target: Element) {
      this.callback([{ target, contentRect: BOX }] as never, this as never)
    }
    unobserve() {}
    disconnect() {}
  } as never

  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
    configurable: true,
    value: BOX.width,
  })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    value: BOX.height,
  })
}

/**
 * Read the tooltip of the first datum.
 *
 * jsdom reports no coordinates, so a hover never lands on a mark. Recharts
 * also walks its data with the arrow keys, which needs no geometry at all.
 */
export function readFirstTooltip(container: HTMLElement): string {
  const surface = container.querySelector('.recharts-surface')
  if (!surface) throw new Error('the chart drew no surface')

  fireEvent.focus(surface)
  fireEvent.keyDown(surface, { key: 'ArrowRight' })

  return document.querySelector('.recharts-tooltip-wrapper')?.textContent ?? ''
}
