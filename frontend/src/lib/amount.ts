import { z } from 'zod'

import { toMinor } from '@/lib/money'

/**
 * A typed amount, as minor units.
 *
 * People type "42.50" or "42,50" depending on their keyboard and locale, so
 * both separators are accepted, and the result is the integer the API takes.
 */
export function amountSchema(options?: { currency?: string; allowZero?: boolean }) {
  const currency = options?.currency ?? 'EUR'
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
}
