import { describe, expect, it } from 'vitest'

import {
  formatPrice,
  formatPriceInput,
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
function quantity(value: string, locale?: string) {
  const result = quantitySchema({ locale }).safeParse(value)
  return result.success ? result.data : result.error.issues[0].message
}

/** The scaled price a typed string reaches the API as, or the message shown. */
function price(value: string, currency = 'EUR', locale?: string) {
  const result = priceSchema(currency, { locale }).safeParse(value)
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

describe('separators in a quantity', () => {
  // A thousands separator is read as one, so "1,200" units is twelve hundred
  // shares to an en-US reader rather than one and a fifth. It is the separator
  // `formatQuantity` writes the holding back with, so typing it in is the
  // natural thing to do. #139.
  it.each([
    ['1,200', 1200 * MICRO],
    ['1,200.5', 1_200_500_000],
    ['12,345,678', 12_345_678 * MICRO],
    // Only one separator, and not in a group's place: a decimal point.
    ['1,20', 1_200_000],
    ['1,2', 1_200_000],
    ['1,253456', 1_253_456],
    [',5', 500_000],
  ])('reads %j as %i scaled units in en-US', (typed, micro) => {
    expect(quantity(typed, 'en-US')).toBe(micro)
  })

  it.each([
    ['1.200', 1200 * MICRO],
    ['1.200,5', 1_200_500_000],
    ['1,200', 1_200_000],
    ['1,2', 1_200_000],
  ])('reads %j as %i scaled units in de-DE', (typed, micro) => {
    expect(quantity(typed, 'de-DE')).toBe(micro)
  })

  it.each([['1,2,3'], ['1,23,456'], ['1,200,50']])('reports %j as not a number', (typed) => {
    expect(quantity(typed, 'en-US')).toBe('Enter a number.')
  })
})

describe('separators in a price', () => {
  // The same figure, and the same separator `formatPrice` renders it back
  // with: a €1,200 share priced as 1.2 is a holding worth a thousandth of
  // what it should be, with nothing on the form saying so.
  it.each([
    ['1,200', 120_000_000_000],
    ['1,200.4567', 120_045_670_000],
    ['1,20', 120_000_000],
  ])('reads %j as %i scaled price in en-US', (typed, micro) => {
    expect(price(typed, 'EUR', 'en-US')).toBe(micro)
  })

  it.each([
    ['1.200', 120_000_000_000],
    ['1.200,4567', 120_045_670_000],
    ['1,200', 120_000_000],
  ])('reads %j as %i scaled price in de-DE', (typed, micro) => {
    expect(price(typed, 'EUR', 'de-DE')).toBe(micro)
  })

  it('takes the narrow space fr-FR groups with', () => {
    expect(price('1\u202f200,45', 'EUR', 'fr-FR')).toBe(120_045_000_000)
  })

  it('reads the decimal point ar-EG writes', () => {
    expect(price('1200\u066b45', 'EUR', 'ar-EG')).toBe(120_045_000_000)
  })
})

describe('formatPriceInput', () => {
  it.each([
    [120_045_670_000, 'EUR', 'en-US', '1200.4567'],
    [120_045_670_000, 'EUR', 'de-DE', '1200,4567'],
    [100_500_000, 'EUR', 'de-DE', '1,005'],
    [3200 * MICRO, 'JPY', 'de-DE', '3200'],
    // No group marks, so nothing in the field is ambiguous to read back.
    [123_456_700_000_000, 'EUR', 'en-IN', '1234567'],
    // A decimal point that is neither "." nor ",".
    [120_045_670_000, 'EUR', 'ar-EG', '1200\u066b4567'],
  ])('writes %i %s as %j in %s', (micro, currency, locale, text) => {
    expect(formatPriceInput(micro, currency, locale)).toBe(text)
  })

  it.each([
    [120_045_670_000, 'EUR', 'en-US'],
    [120_045_670_000, 'EUR', 'de-DE'],
    // A price whose fraction is a group's worth of digits: written with a dot,
    // a locale that groups with one read it back a thousand times over.
    [100_500_000, 'EUR', 'de-DE'],
    [100_500_000, 'EUR', 'en-US'],
    [100_500_000, 'EUR', 'ar-EG'],
    [3200 * MICRO, 'JPY', 'de-DE'],
    [123_456_700_000_000, 'EUR', 'en-IN'],
  ])('round-trips %i %s through the schema in %s', (micro, currency, locale) => {
    const text = formatPriceInput(micro, currency, locale)
    expect(priceSchema(currency, { locale }).parse(text)).toBe(micro)
  })
})
