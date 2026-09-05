import { RecurrenceFrequency } from '@/api'

/**
 * How often a client is seen.
 *
 * Stored as the same (frequency, interval, anchor date) triple that recurring
 * rules use, because it is the same question and the date arithmetic behind it
 * is already written. Offered here as a short list of presets, because nobody
 * thinks in intervals: they think "every other Tuesday".
 */
export type CadencePreset = {
  value: string
  label: string
  frequency: RecurrenceFrequency | null
  interval: number
}

/** No settled pattern: somebody seen as and when. */
export const AD_HOC = 'ad-hoc'

export const CADENCE_PRESETS: CadencePreset[] = [
  { value: AD_HOC, label: 'No set pattern', frequency: null, interval: 1 },
  { value: 'daily', label: 'Every day', frequency: RecurrenceFrequency.DAILY, interval: 1 },
  { value: 'weekly', label: 'Every week', frequency: RecurrenceFrequency.WEEKLY, interval: 1 },
  {
    value: 'fortnightly',
    label: 'Every 2 weeks',
    frequency: RecurrenceFrequency.WEEKLY,
    interval: 2,
  },
  {
    value: 'four-weekly',
    label: 'Every 4 weeks',
    frequency: RecurrenceFrequency.WEEKLY,
    interval: 4,
  },
  { value: 'monthly', label: 'Every month', frequency: RecurrenceFrequency.MONTHLY, interval: 1 },
]

/**
 * The week, Monday first, with Monday as 0 to match the API.
 *
 * Names come from the browser's own locale rather than a hardcoded list, so a
 * German user sees "Mo" without the app shipping a translation table.
 */
export const WEEKDAYS = Array.from({ length: 7 }, (_, day) => {
  // 5 January 1970 was a Monday, so this walks Monday to Sunday.
  const date = new Date(Date.UTC(1970, 0, 5 + day))
  return {
    day,
    short: new Intl.DateTimeFormat(undefined, { weekday: 'short', timeZone: 'UTC' }).format(date),
    long: new Intl.DateTimeFormat(undefined, { weekday: 'long', timeZone: 'UTC' }).format(date),
  }
})

/** Whether a frequency is the one that can name days of the week. */
export function isWeekly(frequency: RecurrenceFrequency | null | undefined): boolean {
  return frequency === RecurrenceFrequency.WEEKLY
}

/** Match a stored (frequency, interval) back to the preset that produced it. */
export function presetOf(
  frequency: RecurrenceFrequency | null | undefined,
  interval: number,
): string {
  if (!frequency) return AD_HOC

  return (
    CADENCE_PRESETS.find((one) => one.frequency === frequency && one.interval === interval)
      ?.value ??
    // A pattern typed straight into the API rather than picked here. Naming it
    // by its frequency is better than silently showing "No set pattern".
    frequency
  )
}

const WEEKDAY = new Intl.DateTimeFormat(undefined, { weekday: 'long' })
const DAY_OF_MONTH = new Intl.DateTimeFormat(undefined, { day: 'numeric' })

/**
 * Say a client's pattern the way a person would.
 *
 * The anchor date is what makes the phrase specific: a weekly pattern keeps
 * that weekday for ever, a monthly one keeps its day of the month, so
 * "every 2 weeks" becomes "every 2 weeks on Monday".
 */
export function describeCadence(
  frequency: RecurrenceFrequency | null | undefined,
  interval: number,
  anchorOn: string | null | undefined,
  weekdays?: number[] | null,
): string {
  if (!frequency) return 'As and when'

  const anchor = anchorOn ? new Date(`${anchorOn}T00:00:00`) : null

  if (frequency === RecurrenceFrequency.DAILY) {
    return interval === 1 ? 'Every day' : `Every ${interval} days`
  }

  if (frequency === RecurrenceFrequency.WEEKLY) {
    // Named days win over the anchor's own weekday: once somebody is seen on
    // four days, the day the pattern started is no longer the useful fact.
    const named = weekdays?.length
      ? weekdays
          .map((one) => WEEKDAYS[one]?.short)
          .filter(Boolean)
          .join(', ')
      : anchor
        ? WEEKDAY.format(anchor)
        : ''
    const day = named ? ` on ${named}` : ''

    return interval === 1 ? `Every week${day}` : `Every ${interval} weeks${day}`
  }

  if (frequency === RecurrenceFrequency.MONTHLY) {
    const day = anchor ? ` on the ${DAY_OF_MONTH.format(anchor)}` : ''
    return interval === 1 ? `Every month${day}` : `Every ${interval} months${day}`
  }

  return interval === 1 ? 'Every year' : `Every ${interval} years`
}
