import { describe, expect, it } from 'vitest'

import {
  formatAmount,
  formatCompactAmount,
  formatMoney,
  formatSignedMoney,
  toMajor,
  toMinor,
} from '@/lib/money'

// Every helper divides or multiplies by the exponent of the currency it was
// given, not by a constant 100. The zero- and three-decimal cases are the ones
// a hardcoded 100, or a helper that assumed EUR, would get wrong.
describe('toMajor', () => {
  it('divides a two-decimal currency by a hundred', () => {
    expect(toMajor(4250, 'EUR')).toBe(42.5)
  })

  it('does not divide a zero-decimal currency', () => {
    expect(toMajor(4250, 'JPY')).toBe(4250)
  })

  it('divides a three-decimal currency by a thousand', () => {
    expect(toMajor(4250, 'BHD')).toBe(4.25)
  })
})

describe('toMinor', () => {
  it('multiplies a two-decimal currency by a hundred', () => {
    expect(toMinor(42.5, 'EUR')).toBe(4250)
  })

  it('does not multiply a zero-decimal currency', () => {
    expect(toMinor(4250, 'JPY')).toBe(4250)
  })

  it('multiplies a three-decimal currency by a thousand', () => {
    expect(toMinor(4.25, 'BHD')).toBe(4250)
  })
})

describe('formatMoney', () => {
  it('shows the minor units of the currency it was given', () => {
    expect(formatMoney(4250, 'EUR')).toContain('42.50')
    expect(formatMoney(4250, 'JPY')).toContain('4,250')
    expect(formatMoney(4250, 'BHD')).toContain('4.250')
  })
})

describe('formatSignedMoney', () => {
  it('signs a positive figure and scales it by the currency', () => {
    expect(formatSignedMoney(4250, 'EUR')).toContain('+')
    expect(formatSignedMoney(4250, 'EUR')).toContain('42.50')
    expect(formatSignedMoney(4250, 'JPY')).toContain('4,250')
  })
})

describe('formatAmount', () => {
  it('uses as many decimals as the currency has', () => {
    expect(formatAmount(4250, 'EUR')).toBe('42.50')
    expect(formatAmount(4250, 'JPY')).toBe('4,250')
    expect(formatAmount(4250, 'BHD')).toBe('4.250')
  })
})

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

// The currency is required, not an option with a default: a caller that does
// not say which currency it renders is a type error, so a new money surface
// cannot be silently wrong the moment a second currency exists.
describe('the currency parameter', () => {
  it('is required by every helper', () => {
    // @ts-expect-error the currency is required
    expect(() => toMajor(4250)).toThrow()
    // @ts-expect-error the currency is required
    expect(() => toMinor(42.5)).toThrow()
    // @ts-expect-error the currency is required
    expect(() => formatMoney(4250)).toThrow()
    // @ts-expect-error the currency is required
    expect(() => formatSignedMoney(4250)).toThrow()
    // @ts-expect-error the currency is required
    expect(() => formatAmount(4250)).toThrow()
    // @ts-expect-error the currency is required
    expect(() => formatCompactAmount(4250)).toThrow()
  })
})
