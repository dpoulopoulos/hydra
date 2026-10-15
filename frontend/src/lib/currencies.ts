/**
 * The currencies an account can be kept in, and how a set of per-currency
 * totals is shown.
 *
 * The list comes from the browser rather than from a table kept here: `Intl`
 * already knows every ISO 4217 code it can format, which is exactly the set
 * worth offering, since an amount in a currency it cannot format could not be
 * shown anyway.
 */

/** A total in one currency, as the API reports several of them side by side. */
export interface CurrencyAmount {
  currency_code: string
  amount_minor: number
}

/** Get a currency's name in the reader's language, e.g. "US Dollar" for USD. */
export function currencyName(code: string, locale?: string): string {
  try {
    return new Intl.DisplayNames(locale, { type: 'currency' }).of(code) ?? code
  } catch {
    return code
  }
}

/**
 * List the currencies to offer, as code and name, ordered by code.
 *
 * `also` is added if the browser does not list it, so an account already kept
 * in an unusual code still shows its own currency rather than an empty field.
 */
export function currencyOptions(locale?: string, also?: string): { code: string; label: string }[] {
  const codes = new Set(Intl.supportedValuesOf('currency'))
  if (also) codes.add(also)

  return [...codes]
    .sort()
    .map((code) => ({ code, label: `${code} — ${currencyName(code, locale)}` }))
}

/**
 * Order per-currency totals with the household's own first.
 *
 * The household's currency is the one every report is in, so it leads; the
 * rest follow by code, which is how the API already sends them.
 */
export function homeFirst<T extends CurrencyAmount>(totals: T[], home: string): T[] {
  return [
    ...totals.filter((total) => total.currency_code === home),
    ...totals.filter((total) => total.currency_code !== home),
  ]
}
