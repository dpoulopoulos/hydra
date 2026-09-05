import { describe, expect, it } from 'vitest'

import { formatCompactAmount } from '@/lib/money'

// A chart axis labels a value that is held in minor units, so the helper has
// to divide by the currency's own exponent before it shortens the number. The
// zero-decimal cases are the ones a hardcoded 100 would get wrong.
describe('formatCompactAmount', () => {
  it('shortens a two-decimal currency', () => {
    expect(formatCompactAmount(1_234_500, 'EUR')).toBe('12K')
  })

  it('rounds a small two-decimal amount to a whole tick', () => {
    expect(formatCompactAmount(4250, 'EUR')).toBe('43')
  })

  it('does not divide a zero-decimal currency', () => {
    expect(formatCompactAmount(500_000, 'JPY')).toBe('500K')
  })

  it('divides a three-decimal currency by its own exponent', () => {
    expect(formatCompactAmount(12_000_000, 'BHD')).toBe('12K')
  })
})
