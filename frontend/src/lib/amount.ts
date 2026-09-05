import { z } from 'zod'

import { toMinor } from '@/lib/money'

/**
 * The largest amount a form accepts, in minor units.
 *
 * The API caps every amount far above this, but past Number.MAX_SAFE_INTEGER a
 * JavaScript number no longer holds an exact integer, so what would be sent is
 * not what was typed. Bounding it here keeps an absurd amount an inline message
 * on the field rather than a rejected request.
 */
export const MAX_AMOUNT_MINOR = Number.MAX_SAFE_INTEGER

/**
 * A typed amount, as minor units.
 *
 * People type "42.50" or "42,50" depending on their keyboard and locale, so
 * both separators are accepted, and the result is the integer the API takes.
 *
 * The currency is a parameter rather than an option with a default: how many
 * minor units a typed amount stands for is a property of the currency, and a
 * default would let a form render in one currency and parse in another
 * without anything saying so.
 */
export function amountSchema(currency: string, options?: { allowZero?: boolean }) {
  const min = options?.allowZero ? 0 : 1

  return z
    .string()
    .trim()
    .min(1, 'Enter an amount.')
    .transform((value) => value.replace(/\s/g, '').replace(',', '.'))
    .refine((value) => /^\d*\.?\d*$/.test(value) && value !== '.', { message: 'Enter a number.' })
    .transform((value) => toMinor(Number(value), currency))
    .refine((minor) => Number.isFinite(minor) && minor >= min, {
      message: options?.allowZero ? 'Enter zero or more.' : 'Enter an amount above zero.',
    })
    .refine((minor) => minor <= MAX_AMOUNT_MINOR, { message: 'Enter a smaller amount.' })
}
