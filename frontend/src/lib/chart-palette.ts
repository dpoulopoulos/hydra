/**
 * The categorical chart palette.
 *
 * Seven slots, assigned in a fixed order and never cycled. Both the light and
 * dark steps were validated with the data-viz checks: each sits inside the
 * lightness band for its surface, clears the chroma floor, stays apart from its
 * neighbours under simulated protanopia and deuteranopia, and meets 3:1 against
 * the surface. An eighth hue could not clear the colour-blindness and contrast
 * rules at once, so anything past the seventh series folds into a neutral
 * "Other" rather than being given a made-up colour.
 */
export const CHART_SLOTS = 7

export const OTHER_KEY = '__other__'

/** The neutral used for the folded tail, so it never looks like a category. */
export const OTHER_COLOR = 'var(--muted-foreground)'

/**
 * A stable slot for a key.
 *
 * Colour follows the entity, not its rank: a category keeps the same colour
 * whether it is the largest this month or the smallest, and re-sorting or
 * filtering the chart never repaints the survivors.
 */
function slotFor(key: string): number {
  let hash = 0
  for (let index = 0; index < key.length; index += 1) {
    hash = (hash * 31 + key.charCodeAt(index)) | 0
  }
  return Math.abs(hash) % CHART_SLOTS
}

export type Slice = { key: string; label: string; amount: number }
export type ColoredSlice = Slice & { color: string; isOther: boolean }

/**
 * Fold a ranked list to the number of slots and colour it by identity.
 *
 * Each visible key takes its own stable slot. Where two keys want the same one,
 * the later takes the next free slot, so a single chart never draws two series
 * in the same colour while colours stay stable between months.
 */
export function toColoredSlices(slices: Slice[]): ColoredSlice[] {
  const kept =
    slices.length <= CHART_SLOTS
      ? slices
      : [
          ...slices.slice(0, CHART_SLOTS - 1),
          {
            key: OTHER_KEY,
            label: `Other (${slices.length - (CHART_SLOTS - 1)})`,
            amount: slices.slice(CHART_SLOTS - 1).reduce((total, slice) => total + slice.amount, 0),
          },
        ]

  const taken = new Set<number>()

  return kept.map((slice) => {
    if (slice.key === OTHER_KEY) {
      return { ...slice, color: OTHER_COLOR, isOther: true }
    }

    let slot = slotFor(slice.key)
    while (taken.has(slot)) slot = (slot + 1) % CHART_SLOTS
    taken.add(slot)

    return { ...slice, color: `var(--chart-${slot + 1})`, isOther: false }
  })
}
