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

/** The scaled units a typed string reaches the API as, or the message shown. */
function quantity(value: string) {
  const result = quantitySchema().safeParse(value)
  return result.success ? result.data : result.error.issues[0].message
}

/** The scaled price a typed string reaches the API as, or the message shown. */
function price(value: string, currency = 'EUR') {
  const result = priceSchema(currency).safeParse(value)
  return result.success ? result.data : result.error.issues[0].message
}

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
  it.each([
    ['10', 10 * MICRO],
    ['1,5', 1_500_000],
    ['1.5', 1_500_000],
    ['0.253', 253_000],
    ['.5', 500_000],
    ['5.', 5 * MICRO],
  ])('reads %j as %i scaled units', (value, expected) => {
    expect(quantity(value)).toBe(expected)
  })

  it('ignores the space around and inside what was typed', () => {
    expect(quantity('  1 0 0  ')).toBe(100 * MICRO)
  })

  it('rounds a fraction finer than the scale holds', () => {
    expect(quantity('0.0000005')).toBe(1)
  })

  it.each([
    ['', 'Enter how many units.'],
    ['   ', 'Enter how many units.'],
    ['ten', 'Enter a number.'],
    ['1a5', 'Enter a number.'],
    ['.', 'Enter a number.'],
    ['1.5.5', 'Enter a number.'],
    ['-5', 'Enter a number.'],
    ['1e3', 'Enter a number.'],
  ])('rejects %j with %j', (value, message) => {
    expect(quantity(value)).toBe(message)
  })

  it.each(['0', '0.0'])('rejects %j, which is not a holding', (value) => {
    expect(quantity(value)).toBe('Enter more than zero units.')
  })

  it('rejects a number too large to send exactly', () => {
    expect(quantity('999999999999')).toBe('Enter a smaller number.')
  })
})

describe('priceSchema', () => {
  it('scales against the instrument currency it was built for', () => {
    expect(price('128.4567')).toBe(12_845_670_000)
  })

  it('reads a comma as the decimal separator', () => {
    // Which separator a keyboard produces is a matter of locale, not of intent.
    expect(price('128,4567')).toBe(12_845_670_000)
  })

  it('does not give a zero decimal currency cents it has no use for', () => {
    expect(price('3200', 'JPY')).toBe(3200 * MICRO)
  })

  it.each([
    ['', 'Enter the price per unit.'],
    ['abc', 'Enter a number.'],
    ['0', 'Enter a price above zero.'],
  ])('rejects %j with %j', (value, message) => {
    expect(price(value)).toBe(message)
  })

  it('rejects a price too large to send exactly', () => {
    expect(price('999999999')).toBe('Enter a smaller number.')
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
