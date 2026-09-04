/**
 * Money helpers.
 *
 * The API speaks integer minor units throughout: `amount_minor`, `limit_minor`,
 * `current_balance_minor`. Nothing in the app should divide by 100 inline,
 * because the number of minor units in a major one is a property of the
 * currency, not a constant. These helpers ask Intl for it.
 *
 * Every helper takes the currency as a required parameter rather than an
 * option with a default: a surface that does not say which currency it renders
 * is a type error rather than a figure that is right only while every
 * household is EUR.
 */

const fractionDigitsCache = new Map<string, number>()

/** Get how many decimal places a currency uses, e.g. 2 for EUR, 0 for JPY. */
export function fractionDigits(currency: string): number {
  const cached = fractionDigitsCache.get(currency)
  if (cached !== undefined) return cached

  const digits =
    new Intl.NumberFormat(undefined, { style: 'currency', currency }).resolvedOptions()
      .maximumFractionDigits ?? 2
  fractionDigitsCache.set(currency, digits)
  return digits
}

const separatorsCache = new Map<string, NumberSeparators>()

/** Which characters a locale writes numbers with. */
export type NumberSeparators = { decimal: string; group: string }

/**
 * Get the characters a locale separates a number with, e.g. "." and "," for
 * en-US, "," and "." for de-DE.
 *
 * The app formats every figure through Intl, so a reader is shown that
 * locale's separators; anything that reads an amount back has to know the same
 * two characters, or it cannot tell a typed decimal point from a group mark.
 */
export function numberSeparators(locale?: string): NumberSeparators {
  const key = locale ?? ''
  const cached = separatorsCache.get(key)
  if (cached !== undefined) return cached

  const parts = new Intl.NumberFormat(locale).formatToParts(11111.1)
  const separators = {
    decimal: parts.find((part) => part.type === 'decimal')?.value ?? '.',
    group: parts.find((part) => part.type === 'group')?.value ?? ',',
  }
  separatorsCache.set(key, separators)
  return separators
}

const groupingCache = new Map<string, NumberGrouping>()

/** How many digits a locale groups by, the group nearest the decimal point first. */
export type NumberGrouping = { primary: number; secondary: number }

/**
 * Get how many digits a locale groups a number by, e.g. 3 and 3 for en-US,
 * which writes 11111111 as "11,111,111", and 3 and 2 for en-IN, which writes
 * the same number as "1,11,11,111".
 *
 * Reading a grouped number back means knowing where its marks belong, and
 * "a mark every three digits" is only most of the world.
 */
export function numberGrouping(locale?: string): NumberGrouping {
  const key = locale ?? ''
  const cached = groupingCache.get(key)
  if (cached !== undefined) return cached

  // Long enough to carry more than one group mark, so the group before the
  // last one is there to be counted rather than being the leading remainder.
  const runs = new Intl.NumberFormat(locale)
    .formatToParts(11111111)
    .filter((part) => part.type === 'integer')
    .map((part) => part.value.length)

  // A locale that groups nothing says nothing about where a mark belongs, so
  // read marks typed anyway as the threes almost every locale writes.
  const grouping =
    runs.length > 2
      ? { primary: runs[runs.length - 1], secondary: runs[runs.length - 2] }
      : { primary: 3, secondary: 3 }
  groupingCache.set(key, grouping)
  return grouping
}

/** Convert minor units to the major amount, e.g. 4250 -> 42.5 for EUR. */
export function toMajor(minor: number, currency: string): number {
  return minor / 10 ** fractionDigits(currency)
}

/** Convert a major amount to minor units, rounding to the nearest unit. */
export function toMinor(major: number, currency: string): number {
  return Math.round(major * 10 ** fractionDigits(currency))
}

/** Format minor units as currency, e.g. 4250 -> "€42.50". */
export function formatMoney(minor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(
    toMajor(minor, currency),
  )
}

/**
 * Format minor units with an explicit sign, for figures where the direction
 * matters more than the value, such as a month's net.
 */
export function formatSignedMoney(minor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    signDisplay: 'exceptZero',
  }).format(toMajor(minor, currency))
}

/** Format minor units without the currency symbol, for dense tables. */
export function formatAmount(minor: number, currency: string): string {
  const digits = fractionDigits(currency)
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(toMajor(minor, currency))
}

/**
 * Format minor units as a short number, for a chart axis.
 *
 * No currency symbol: an axis repeats its label on every tick, so the symbol
 * belongs to the chart's title, and the ticks only have to stay readable.
 */
export function formatCompactAmount(minor: number, currency: string): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact' }).format(toMajor(minor, currency))
}

/** Format a 0-1 ratio as a whole percentage, e.g. 0.8 -> "80%". */
export function formatPercent(ratio: number): string {
  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 0,
  }).format(ratio)
}

/**
 * Write minor units the way a field is edited, e.g. 120000 -> "1200.5" in
 * en-US and "1200,5" in de-DE.
 *
 * A field filled with a bare `String(toMajor(...))` writes the decimal point
 * as a dot whatever the reader's locale is, and whoever reads the field back
 * has only the characters to go on: in a locale that groups with a dot, a
 * three-decimal currency round-trips "1.005" as a thousand and five. The field
 * is written with the separator that locale reads as a decimal point instead,
 * and with no group marks to be ambiguous about at all.
 */
export function formatMajorInput(minor: number, currency: string, locale?: string): string {
  // Plain `String`, not `Intl`, so the digits are the ASCII ones every field
  // takes; only the character between them is the reader's. That character is
  // whatever the locale reads back as a decimal point, which is not always "."
  // or ",": ar-EG and fa-IR write the Arabic decimal separator, "٫".
  const text = String(toMajor(minor, currency))
  const { decimal } = numberSeparators(locale)
  return decimal === '.' ? text : text.replace('.', decimal)
}
