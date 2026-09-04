import { describe, expect, it } from 'vitest'

import { MAX_AMOUNT_MINOR, amountSchema } from '@/lib/amount'

/** The minor units a typed string reaches the API as, or the message shown. */
function parse(value: string, currency = 'EUR', options?: { allowZero?: boolean }) {
  const result = amountSchema(currency, options).safeParse(value)
  return result.success ? result.data : result.error.issues[0].message
}

describe('amountSchema', () => {
  it.each([
    ['42.50', 4250],
    ['42,50', 4250],
    ['1 000', 100000],
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

  // A thousands separator is read as a decimal point, so "1,000" is a euro
  // rather than a thousand. Pinned as it behaves today, wrong; #18 is the fix,
  // and these two rows are what it has to change.
  it.each([
    ['1,000', 100],
    ['1.000', 100],
  ])('reads the thousands separator in %j as a decimal point', (value, actual) => {
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
    it.each(['99999999999999999', '1' + '0'.repeat(300)])(
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
