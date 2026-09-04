/**
 * Money helpers.
 *
 * The API speaks integer minor units throughout: `amount_minor`, `limit_minor`,
 * `current_balance_minor`. Nothing in the app should divide by 100 inline,
 * because the number of minor units in a major one is a property of the
 * currency, not a constant. These helpers ask Intl for it.
 */

const fractionDigitsCache = new Map<string, number>()

/** Get how many decimal places a currency uses, e.g. 2 for EUR, 0 for JPY. */
function fractionDigits(currency: string): number {
  const cached = fractionDigitsCache.get(currency)
  if (cached !== undefined) return cached

  const digits =
    new Intl.NumberFormat(undefined, { style: 'currency', currency }).resolvedOptions()
      .maximumFractionDigits ?? 2
  fractionDigitsCache.set(currency, digits)
  return digits
}

/** Convert minor units to the major amount, e.g. 4250 -> 42.5 for EUR. */
export function toMajor(minor: number, currency = 'EUR'): number {
  return minor / 10 ** fractionDigits(currency)
}

/** Convert a major amount to minor units, rounding to the nearest unit. */
export function toMinor(major: number, currency = 'EUR'): number {
  return Math.round(major * 10 ** fractionDigits(currency))
}

/** Format minor units as currency, e.g. 4250 -> "€42.50". */
export function formatMoney(minor: number, currency = 'EUR'): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(
    toMajor(minor, currency),
  )
}

/**
 * Format minor units with an explicit sign, for figures where the direction
 * matters more than the value, such as a month's net.
 */
export function formatSignedMoney(minor: number, currency = 'EUR'): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency,
    signDisplay: 'exceptZero',
  }).format(toMajor(minor, currency))
}

/** Format minor units without the currency symbol, for dense tables. */
export function formatAmount(minor: number, currency = 'EUR'): string {
  const digits = fractionDigits(currency)
  return new Intl.NumberFormat(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(toMajor(minor, currency))
}

/** Format a 0-1 ratio as a whole percentage, e.g. 0.8 -> "80%". */
export function formatPercent(ratio: number): string {
  return new Intl.NumberFormat(undefined, {
    style: 'percent',
    maximumFractionDigits: 0,
  }).format(ratio)
}
