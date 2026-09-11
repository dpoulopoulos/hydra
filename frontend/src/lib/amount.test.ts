import { describe, expect, it } from 'vitest'

import { MAX_AMOUNT_MINOR, amountSchema, previewMinor } from '@/lib/amount'

/** The minor units a typed string reaches the API as, or the message shown. */
function parse(
  value: string,
  currency = 'EUR',
  options?: { allowZero?: boolean; locale?: string },
) {
  const result = amountSchema(currency, options).safeParse(value)
  return result.success ? result.data : result.error.issues[0].message
}

// This is the one reading of a typed amount the app has: what a form saves is
// whatever this schema makes of the field. Anything else that reads the same
// field back — a preview sentence, say — has to agree with it, so the shapes
// people actually type are pinned here.
describe('amountSchema', () => {
  it.each([
    ['42.50', 4250],
    ['42,50', 4250],
    ['1 000', 100000],
    ['1 000,50', 100050],
    ['0.01', 1],
    ['0.05', 5],
    ['.5', 50],
    [',5', 50],
    ['5.', 500],
    ['42', 4200],
  ])('reads %j as %d minor units', (value, expected) => {
    expect(parse(value)).toBe(expected)
  })

  it('ignores the space around and inside what was typed', () => {
    expect(parse('  1 0 0  ')).toBe(10000)
  })

  it('rounds a fraction the currency cannot hold', () => {
    expect(parse('42.505')).toBe(4251)
  })

  // A thousands separator is read as one, so "1,000" is a thousand to an en-US
  // reader rather than a euro. A dot there is that reader's decimal point, so
  // "1.000" is the euro. #18.
  it.each([
    ['1,000', 100000],
    ['1.000', 100],
  ])('reads the thousands separator in %j as one', (value, actual) => {
    expect(parse(value)).toBe(actual)
  })

  it.each([
    ['', 'Enter an amount.'],
    ['   ', 'Enter an amount.'],
    ['abc', 'Enter a number.'],
    ['4a2', 'Enter a number.'],
    ['.', 'Enter a number.'],
    ['4.2.5', 'Enter a number.'],
    ['-5', 'Enter a number.'],
    ['12e3', 'Enter a number.'],
    ['€5', 'Enter a number.'],
  ])('rejects %j with %j', (value, message) => {
    expect(parse(value)).toBe(message)
  })

  it.each(['0', '0.00', '0,00'])('rejects %j, which buys nothing', (value) => {
    expect(parse(value)).toBe('Enter an amount above zero.')
  })

  it('takes zero where a form allows it', () => {
    expect(parse('0', 'EUR', { allowZero: true })).toBe(0)
  })

  it('still wants something typed where zero is allowed', () => {
    expect(parse('', 'EUR', { allowZero: true })).toBe('Enter an amount.')
  })

  it('rounds a sub-unit amount up to the minimum rather than to zero', () => {
    expect(parse('0.004')).toBe('Enter an amount above zero.')
  })

  describe('for a currency that is not the euro', () => {
    it('reads a whole yen as one minor unit', () => {
      expect(parse('4250', 'JPY')).toBe(4250)
    })

    it('rounds away the fraction a yen does not have', () => {
      expect(parse('42.50', 'JPY')).toBe(43)
    })

    it('reads three decimals of a dinar', () => {
      expect(parse('4.250', 'BHD')).toBe(4250)
    })
  })

  describe('at the upper bound', () => {
    // The bound holds after the group marks are read, too.
    it.each(['99999999999999999', '99,999,999,999,999,999,999', '1' + '0'.repeat(300)])(
      'rejects %j, which no longer holds what was typed',
      (value) => {
        expect(parse(value)).toBe('Enter a smaller amount.')
      },
    )

    it('takes an amount just under the bound', () => {
      expect(parse('90071992547409')).toBe(9007199254740900)
      expect(9007199254740900).toBeLessThanOrEqual(MAX_AMOUNT_MINOR)
    })
  })
})

describe('separators', () => {
  it.each([
    // A group mark, the way the app itself formats the figure back.
    ['1,200', 120000],
    ['1,200.50', 120050],
    ['12,345,678', 1234567800],
    ['1.200,50', 120050],
    ['1.200.500', 120050000],
    // Only one separator, and not in a group's place: a decimal point.
    ['1,20', 120],
    ['1,2', 120],
    ['1234,567', 123457],
    // Unusual, but a group mark cannot lead.
    [',500', 50],
    // Nor can it follow a padded leading group: this is half a unit.
    ['0,500', 50],
  ])('reads %j as %i minor units in en-US', (typed, minor) => {
    expect(parse(typed, 'EUR', { locale: 'en-US' })).toBe(minor)
  })

  it.each([
    ['1.200', 120000],
    ['1.200,50', 120050],
    ['1,200', 120],
    ['1,20', 120],
    ['1,2', 120],
    ['1.234.567', 123456700],
    ['1234.567', 123457],
    ['0.500', 50],
  ])('reads %j as %i minor units in de-DE', (typed, minor) => {
    expect(parse(typed, 'EUR', { locale: 'de-DE' })).toBe(minor)
  })

  it.each([
    // en-IN groups the lakh, and this is how Intl writes 1234567 back.
    ['12,34,567', 123456700],
    ['12,34,567.50', 123456750],
    ['1,200', 120000],
    ['12,345', 1234500],
    // Three-digit groups carry the same digits, so they read here too.
    ['1,234,567', 123456700],
    ['1,20', 120],
  ])('reads %j as %i minor units in en-IN', (typed, minor) => {
    expect(parse(typed, 'EUR', { locale: 'en-IN' })).toBe(minor)
  })

  it.each([
    ["1'200", 120000],
    ["1'200.50", 120050],
  ])('reads %j as %i minor units in de-CH', (typed, minor) => {
    expect(parse(typed, 'EUR', { locale: 'de-CH' })).toBe(minor)
  })

  it('takes the narrow space fr-FR groups with', () => {
    expect(parse('1\u202f200,50', 'EUR', { locale: 'fr-FR' })).toBe(120050)
  })

  it.each([
    // Its own decimal point, which the field is filled with.
    ['1\u066b5', 150],
    ['1200\u066b50', 120050],
    // Its own group mark, which says nothing about the decimal point.
    ['1\u066c200', 120000],
    // Nothing groups with a dot here, so a typed one is a decimal point. A
    // three-decimal amount read out of a field arrives written like this.
    ['1.200', 120],
    ['1.5', 150],
  ])('reads %j as %i minor units in ar-EG', (typed, minor) => {
    expect(parse(typed, 'EUR', { locale: 'ar-EG' })).toBe(minor)
  })

  it('reads a three-decimal amount written with a dot in ar-EG', () => {
    expect(parse('1.005', 'BHD', { locale: 'ar-EG' })).toBe(1005)
  })

  it.each([['1,2,3'], ['1.2.3'], ['1,2.3,4'], ['1,23,456'], ['1,200,50'], [',']])(
    'reports %j as not a number',
    (typed) => {
      expect(parse(typed, 'EUR', { locale: 'en-US' })).toBe('Enter a number.')
    },
  )
})

// A preview reads the field while it is being typed, before the resolver has
// had anything to say about it, so it needs the same reading of "1 000" the
// saved value gets — and nothing to show while the field is still half typed.
describe('previewMinor', () => {
  it('reads what the schema would save', () => {
    expect(previewMinor('42,50', 'EUR')).toBe(4250)
    expect(previewMinor('1 000', 'EUR')).toBe(100000)
  })

  it('reads zero as zero rather than as nothing typed', () => {
    expect(previewMinor('0', 'EUR')).toBe(0)
  })

  it('has nothing to show for an empty field', () => {
    expect(previewMinor('', 'EUR')).toBeNull()
    expect(previewMinor(undefined, 'EUR')).toBeNull()
  })

  it('has nothing to show for something that is not a number', () => {
    expect(previewMinor('forty two', 'EUR')).toBeNull()
    expect(previewMinor('.', 'EUR')).toBeNull()
  })

  it('has nothing to show for an amount past the ceiling', () => {
    expect(previewMinor(String(MAX_AMOUNT_MINOR), 'EUR')).toBeNull()
  })
})
