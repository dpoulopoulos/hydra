/**
 * Month helpers.
 *
 * Budgets and reports key on a month rather than a date, and the API takes it
 * as "YYYY-MM". These keep that format in one place.
 */

/** The month key of a date, e.g. "2026-03". */
export function monthKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
}

/** This month, as a key. */
export function currentMonth(): string {
  return monthKey(new Date())
}

/** Shift a month key by a number of months, e.g. ("2026-01", -1) -> "2025-12". */
export function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split('-').map(Number)
  return monthKey(new Date(year, monthNumber - 1 + delta, 1))
}

/** The first day of a month, as an ISO date, e.g. "2026-03-01". */
export function monthStart(month: string): string {
  return `${month}-01`
}

/** The last day of a month, as an ISO date, e.g. "2026-03-31". */
export function monthEnd(month: string): string {
  const [year, monthNumber] = month.split('-').map(Number)
  return isoDate(new Date(year, monthNumber, 0))
}

/** Format a date as an ISO date, which is what the API takes. */
export function isoDate(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(
    date.getDate(),
  ).padStart(2, '0')}`
}

/** Today, as an ISO date. */
export function today(): string {
  return isoDate(new Date())
}

/** A month key rendered for people, e.g. "March 2026". */
export function formatMonth(month: string, options?: Intl.DateTimeFormatOptions): string {
  const [year, monthNumber] = month.split('-').map(Number)
  return new Intl.DateTimeFormat(undefined, options ?? { month: 'long', year: 'numeric' }).format(
    new Date(year, monthNumber - 1, 1),
  )
}

/**
 * An ISO date rendered for people, e.g. "4 Mar 2026".
 *
 * The date is read as a calendar date rather than parsed, so a plain
 * "2026-03-04" is not taken for UTC midnight and shown as the third to anyone
 * west of Greenwich. That makes this the wrong formatter for a tz-aware
 * timestamp, whose instant it would truncate: use `formatInstantAsDate` or
 * `formatDateTime` for those.
 */
export function formatDate(value: string, options?: Intl.DateTimeFormatOptions): string {
  const [year, month, day] = value.slice(0, 10).split('-').map(Number)
  return new Intl.DateTimeFormat(
    undefined,
    options ?? { day: 'numeric', month: 'short', year: 'numeric' },
  ).format(new Date(year, month - 1, day))
}

/**
 * A timestamp rendered for people as a date alone, e.g. "4 Mar 2026".
 *
 * Unlike `formatDate` this converts the instant to the viewer's timezone
 * first, which is what a tz-aware value wants: parsing is unambiguous here
 * precisely because the value carries an offset.
 */
export function formatInstantAsDate(value: string, options?: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(
    undefined,
    options ?? { day: 'numeric', month: 'short', year: 'numeric' },
  ).format(new Date(value))
}

/** A timestamp rendered for people, e.g. "4 Mar 2026, 14:30". */
export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
