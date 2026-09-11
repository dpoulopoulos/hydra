import { z } from 'zod'

import { parseMajor } from '@/lib/amount'
import { fractionDigits, numberSeparators } from '@/lib/money'

/**
 * Quantity and unit price helpers.
 *
 * Money is exact in this app because the API speaks whole minor units. A
 * holding cannot be: it is a fraction of a unit at a price quoted to more
 * decimal places than a currency has. So the API carries both scaled by MICRO,
 * as integers, and these convert at the edges. Nothing multiplies a quantity
 * by a price here; that is the server's job, and doing it in both places is
 * how the two answers start to differ.
 */
export const MICRO = 1_000_000

/**
 * The largest scaled value a form accepts.
 *
 * The API caps both further down, but past Number.MAX_SAFE_INTEGER a
 * JavaScript number stops holding an exact integer, so what would be sent is
 * no longer what was typed.
 */
const MAX_MICRO = Number.MAX_SAFE_INTEGER

/** Convert a number of units to the scaled integer the API takes. */
export function toQuantityMicro(units: number): number {
  return Math.round(units * MICRO)
}

/** Convert the API's scaled quantity back to a number of units. */
export function fromQuantityMicro(micro: number): number {
  return micro / MICRO
}

/**
 * Convert a unit price in major units to the scaled integer the API takes.
 *
 * A price carries two scales: the currency's own, which turns 128.45 into
 * 12845, and MICRO on top of that, which is what keeps the 67 in 128.4567.
 */
export function toPriceMicro(major: number, currency = 'EUR'): number {
  return Math.round(major * 10 ** fractionDigits(currency) * MICRO)
}

/** Convert the API's scaled price back to major units. */
export function fromPriceMicro(micro: number, currency = 'EUR'): number {
  return micro / (10 ** fractionDigits(currency) * MICRO)
}

/**
 * Format a quantity of units.
 *
 * Trailing zeroes are dropped, so a whole number of shares reads as "10"
 * rather than "10.000000", while a fractional holding keeps its precision.
 *
 * Written in the household's locale, like the money it sits beside: leaving it
 * out means the reader's own browser.
 */
export function formatQuantity(micro: number, locale?: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(
    fromQuantityMicro(micro),
  )
}

/**
 * Format a unit price, in its own currency.
 *
 * Shown to four decimal places rather than the currency's two, because that is
 * the precision an ETF is actually quoted at and rounding it on screen makes
 * the value look like it does not follow from the price.
 */
export function formatPrice(micro: number, currency = 'EUR', locale?: string): string {
  const digits = fractionDigits(currency)
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: Math.max(digits, 4),
  }).format(fromPriceMicro(micro, currency))
}

/**
 * Write a price the way its field is edited, e.g. 100500000 -> "1.005" in
 * en-US and "1,005" in de-DE.
 *
 * The sibling of `formatMajorInput` for the scale a price carries. A field
 * filled with a bare `String(fromPriceMicro(...))` writes the decimal point as
 * a dot whatever the reader's locale is, and whoever reads the field back has
 * only the characters to go on: in a locale that groups with a dot, a price of
 * 1.005 round-trips as a thousand and five.
 */
export function formatPriceInput(micro: number, currency: string, locale?: string): string {
  // Plain `String`, not `Intl`, so the digits are the ASCII ones every field
  // takes and no group mark is written for the parser to be unsure about; only
  // the character between them is the reader's.
  const text = String(fromPriceMicro(micro, currency))
  const { decimal } = numberSeparators(locale)
  return decimal === '.' ? text : text.replace('.', decimal)
}

/**
 * A typed decimal, as a scaled integer.
 *
 * The string is read by `parseMajor`, the same parser the amount fields use,
 * so a quantity or a price written the way the app writes it back is read as
 * the figure the reader was shown. Only the scale differs: what comes out is
 * in units or in a currency's major units, and `scale` carries it to MICRO.
 */
function scaledSchema(
  scale: (value: number) => number,
  messages: { empty: string; min: string },
  locale?: string,
) {
  return z
    .string()
    .trim()
    .min(1, messages.empty)
    .transform((value, ctx) => {
      const major = parseMajor(value, locale)
      if (major === null) {
        ctx.addIssue({ code: 'custom', message: 'Enter a number.' })
        return z.NEVER
      }
      return scale(major)
    })
    .refine((micro) => Number.isFinite(micro) && micro > 0, { message: messages.min })
    .refine((micro) => micro <= MAX_MICRO, { message: 'Enter a smaller number.' })
}

/**
 * Format an exchange rate, e.g. 860440 -> "0.860440".
 *
 * Shown to six decimals, and padded rather than trimmed. A rate is compared
 * against the one a bank or a broker quotes, and a trimmed "0.86" cannot be
 * checked against "0.860440" at a glance.
 */
export function formatRate(micro: number, locale?: string): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 6,
    maximumFractionDigits: 6,
  }).format(micro / MICRO)
}

/** A typed number of units, as the scaled integer the API takes. */
export function quantitySchema(options?: { locale?: string }) {
  return scaledSchema(
    toQuantityMicro,
    { empty: 'Enter how many units.', min: 'Enter more than zero units.' },
    options?.locale,
  )
}

/** A typed unit price, as the scaled integer the API takes. */
export function priceSchema(currency: string, options?: { locale?: string }) {
  return scaledSchema(
    (value) => toPriceMicro(value, currency),
    { empty: 'Enter the price per unit.', min: 'Enter a price above zero.' },
    options?.locale,
  )
}
