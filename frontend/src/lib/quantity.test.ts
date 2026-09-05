import { describe, expect, it } from 'vitest'

import {
  formatPrice,
  formatQuantity,
  formatRate,
  fromPriceMicro,
  fromQuantityMicro,
  MICRO,
  priceSchema,
  quantitySchema,
  toPriceMicro,
  toQuantityMicro,
} from '@/lib/quantity'

describe('quantities', () => {
  it('scales a whole number of units', () => {
    expect(toQuantityMicro(10)).toBe(10 * MICRO)
  })

  it('keeps a fraction of a unit', () => {
    // Fractional shares are ordinary now, so losing the fraction would lose
    // most of what a small holding is.
    expect(toQuantityMicro(0.253)).toBe(253_000)
  })

  it('round trips', () => {
    expect(fromQuantityMicro(toQuantityMicro(1.5))).toBe(1.5)
  })

  it('drops trailing zeroes when formatting', () => {
    expect(formatQuantity(10 * MICRO)).toBe('10')
  })

  it('keeps precision when formatting a fraction', () => {
    expect(formatQuantity(253_000)).toBe('0.253')
  })
})

describe('prices', () => {
  it('carries both the currency scale and the extra precision', () => {
    // 128.4567 EUR is 12845.67 cents, and it is the ".67" that the MICRO scale
    // exists to keep: rounding it away is a real loss on a large holding.
    expect(toPriceMicro(128.4567, 'EUR')).toBe(12_845_670_000)
  })

  it('does not give a zero decimal currency cents it has no use for', () => {
    expect(toPriceMicro(3200, 'JPY')).toBe(3200 * MICRO)
  })

  it('round trips', () => {
    expect(fromPriceMicro(toPriceMicro(128.4567, 'EUR'), 'EUR')).toBeCloseTo(128.4567, 6)
  })

  it('formats to more decimals than the currency has', () => {
    // Showing 128.46 next to a value derived from 128.4567 makes the value look
    // like it does not follow from the price.
    expect(formatPrice(12_845_670_000, 'EUR')).toContain('128.4567')
  })
})

describe('quantitySchema', () => {
  it('accepts a comma as the decimal separator', () => {
    // Which separator a keyboard produces is a matter of locale, not of intent.
    expect(quantitySchema().parse('1,5')).toBe(toQuantityMicro(1.5))
  })

  it('rejects zero units', () => {
    expect(quantitySchema().safeParse('0').success).toBe(false)
  })

  it('rejects something that is not a number', () => {
    expect(quantitySchema().safeParse('ten').success).toBe(false)
  })

  it('rejects a number too large to send exactly', () => {
    expect(quantitySchema().safeParse('999999999999').success).toBe(false)
  })
})

describe('priceSchema', () => {
  it('scales against the instrument currency it was built for', () => {
    expect(priceSchema('EUR').parse('128.4567')).toBe(12_845_670_000)
  })

  it('rejects a price of zero', () => {
    expect(priceSchema('EUR').safeParse('0').success).toBe(false)
  })
})

describe('formatRate', () => {
  it('shows six decimals so it can be checked against a quoted rate', () => {
    expect(formatRate(860_440)).toBe('0.860440')
  })

  it('pads a short rate rather than trimming it', () => {
    expect(formatRate(900_000)).toBe('0.900000')
  })

  it('handles a rate above one', () => {
    expect(formatRate(1_162_500)).toBe('1.162500')
  })
})
