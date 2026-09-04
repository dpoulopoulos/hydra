import { describe, expect, it } from 'vitest'

import {
  formatAmount,
  formatCompactAmount,
  formatMoney,
  formatPercent,
  formatSignedMoney,
  numberGrouping,
  numberSeparators,
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

  it('keeps the sign of a negative balance', () => {
    expect(toMajor(-4250, 'EUR')).toBe(-42.5)
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

  it.each([
    [42.494, 4249],
    [42.495, 4250],
    [42.499, 4250],
  ])('rounds %d to the nearest minor unit', (major, expected) => {
    expect(toMinor(major, 'EUR')).toBe(expected)
  })

  it('rounds away the fraction a zero-decimal currency cannot hold', () => {
    expect(toMinor(4250.6, 'JPY')).toBe(4251)
  })

  it('returns an integer for an amount binary floating point cannot hold', () => {
    expect(toMinor(1.1 + 2.2, 'EUR')).toBe(330)
  })
})

// A minor amount has to survive the trip out to a form field and back, or
// editing a record without touching the amount would change it.
describe('toMinor and toMajor', () => {
  it.each(['EUR', 'JPY', 'BHD'])('round trip through %s', (currency) => {
    for (const minor of [0, 1, 7, 999, 123456, -4250]) {
      expect(toMinor(toMajor(minor, currency), currency)).toBe(minor)
    }
  })
})

describe('formatMoney', () => {
  it('shows the minor units of the currency it was given', () => {
    expect(formatMoney(4250, 'EUR')).toContain('42.50')
    expect(formatMoney(4250, 'JPY')).toContain('4,250')
    expect(formatMoney(4250, 'BHD')).toContain('4.250')
  })

  it('renders a negative amount with a minus sign', () => {
    expect(formatMoney(-4250, 'EUR')).toContain('-')
    expect(formatMoney(-4250, 'EUR')).toContain('42.50')
  })
})

describe('formatSignedMoney', () => {
  it('signs a positive figure and scales it by the currency', () => {
    expect(formatSignedMoney(4250, 'EUR')).toContain('+')
    expect(formatSignedMoney(4250, 'EUR')).toContain('42.50')
    expect(formatSignedMoney(4250, 'JPY')).toContain('4,250')
  })

  it('signs a negative figure', () => {
    expect(formatSignedMoney(-4250, 'EUR')).toContain('-')
  })

  // signDisplay: 'exceptZero', so a month that netted nothing reads as a
  // figure rather than as a direction.
  it('leaves zero unsigned', () => {
    expect(formatSignedMoney(0, 'EUR')).not.toContain('+')
    expect(formatSignedMoney(0, 'EUR')).not.toContain('-')
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

describe('formatPercent', () => {
  it.each([
    [0, '0%'],
    [0.8, '80%'],
    [1, '100%'],
    [1.256, '126%'],
  ])('renders %d as a whole percentage', (ratio, expected) => {
    expect(formatPercent(ratio)).toBe(expected)
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
    // @ts-expect-error the currency is required
    expect(() => formatMajorInput(4250)).toThrow()
  })
})

describe('numberSeparators', () => {
  it.each([
    ['en-US', '.', ','],
    ['en-GB', '.', ','],
    ['de-DE', ',', '.'],
    ['fr-FR', ',', '\u202f'], // a narrow no-break space
    ['de-CH', '.', "'"],
    // Neither of its separators is one of "." and ",".
    ['ar-EG', '\u066b', '\u066c'],
    ['fa-IR', '\u066b', '\u066c'],
  ])('reports %s as decimal %j and group %j', (locale, decimal, group) => {
    expect(numberSeparators(locale)).toEqual({ decimal, group })
  })

  it('falls back to the runtime locale', () => {
    const runtime = new Intl.NumberFormat().resolvedOptions().locale
    expect(numberSeparators()).toEqual(numberSeparators(runtime))
  })
})

describe('numberGrouping', () => {
  it.each([
    ['en-US', 3, 3],
    ['de-DE', 3, 3],
    ['fr-FR', 3, 3],
    ['en-IN', 3, 2], // the lakh: 1234567 is written "12,34,567"
    ['hi-IN', 3, 2],
  ])('reports %s as groups of %i and %i digits', (locale, primary, secondary) => {
    expect(numberGrouping(locale)).toEqual({ primary, secondary })
  })

  it('falls back to the runtime locale', () => {
    const runtime = new Intl.NumberFormat().resolvedOptions().locale
    expect(numberGrouping()).toEqual(numberGrouping(runtime))
  })
})
