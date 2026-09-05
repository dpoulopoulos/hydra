import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  currentMonth,
  formatDate,
  formatDateTime,
  formatInstantAsDate,
  formatMonth,
  isoDate,
  monthEnd,
  monthKey,
  monthStart,
  shiftMonth,
  today,
} from '@/lib/month'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllEnvs()
})

/** Freeze the clock, so the helpers that read it can be asserted. */
function nowIs(instant: string) {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(instant))
}

// The suite formats in UTC, so a case about which day a value lands on has to
// move the viewer off it. Node rereads TZ on every date it builds, so setting
// it is enough.
function viewerIn(timeZone: string) {
  vi.stubEnv('TZ', timeZone)
}

/** The same options the formatters default to, rendered by the same locale. */
function formatted(date: Date, options?: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat(
    undefined,
    options ?? { day: 'numeric', month: 'short', year: 'numeric' },
  ).format(date)
}

describe('monthKey', () => {
  it.each([
    [new Date(2026, 2, 4), '2026-03'],
    [new Date(2026, 0, 1), '2026-01'],
    [new Date(2026, 11, 31), '2026-12'],
  ])('keys %s as %s', (date, expected) => {
    expect(monthKey(date)).toBe(expected)
  })
})

describe('isoDate', () => {
  it.each([
    [new Date(2026, 2, 4), '2026-03-04'],
    [new Date(2026, 11, 31), '2026-12-31'],
  ])('renders %s as %s', (date, expected) => {
    expect(isoDate(date)).toBe(expected)
  })

  it('reads the local calendar day rather than the UTC one', () => {
    // Late on the 4th in UTC is already the 5th further east, and it is the
    // day on the wall that a person means when they date a transaction.
    expect(isoDate(new Date(2026, 2, 4, 23, 30))).toBe('2026-03-04')
  })
})

describe('currentMonth and today', () => {
  it('read the clock', () => {
    nowIs('2026-03-04T12:00:00Z')
    expect(currentMonth()).toBe('2026-03')
    expect(today()).toBe('2026-03-04')
  })

  it('roll over at the end of a month', () => {
    nowIs('2026-12-31T23:59:59Z')
    expect(currentMonth()).toBe('2026-12')
    expect(today()).toBe('2026-12-31')
  })
})

describe('shiftMonth', () => {
  it.each([
    ['2026-03', 1, '2026-04'],
    ['2026-03', -1, '2026-02'],
    ['2026-03', 0, '2026-03'],
    ['2026-01', -1, '2025-12'],
    ['2026-12', 1, '2027-01'],
    ['2026-03', 12, '2027-03'],
    ['2026-03', -14, '2025-01'],
  ])('shifts %s by %d to %s', (month, delta, expected) => {
    expect(shiftMonth(month, delta)).toBe(expected)
  })

  it('walks back to where it started', () => {
    expect(shiftMonth(shiftMonth('2026-01', -1), 1)).toBe('2026-01')
  })
})

describe('monthStart and monthEnd', () => {
  it.each([
    ['2026-03', '2026-03-01', '2026-03-31'],
    ['2026-04', '2026-04-01', '2026-04-30'],
    ['2026-02', '2026-02-01', '2026-02-28'],
    ['2024-02', '2024-02-01', '2024-02-29'],
    ['2026-12', '2026-12-01', '2026-12-31'],
  ])('bound %s as %s to %s', (month, start, end) => {
    expect(monthStart(month)).toBe(start)
    expect(monthEnd(month)).toBe(end)
  })
})

describe('formatMonth', () => {
  it('names the month and the year', () => {
    expect(formatMonth('2026-03')).toBe('March 2026')
  })

  it('takes the shape the caller asks for', () => {
    expect(formatMonth('2026-03', { month: 'short', year: '2-digit' })).toBe('Mar 26')
  })

  it('reads January as the first month, not the zeroth', () => {
    expect(formatMonth('2026-01')).toBe('January 2026')
    expect(formatMonth('2026-12')).toBe('December 2026')
  })
})

describe('formatDate', () => {
  it.each([
    ['2026-03-04', 'Mar 4, 2026'],
    ['2026-01-01', 'Jan 1, 2026'],
    ['2026-12-31', 'Dec 31, 2026'],
  ])('renders %s as %s', (value, expected) => {
    expect(formatDate(value)).toBe(expected)
  })

  it('takes the shape the caller asks for', () => {
    expect(formatDate('2026-03-04', { day: 'numeric', month: 'long' })).toBe('March 4')
  })

  // The three callers that pass a timestamp get the UTC calendar day, because
  // the time and the zone are cut off before the date is built. It reads right
  // from UTC and a day off elsewhere; #36 is the fix.
  it('cuts the time off a timestamp instead of converting it', () => {
    expect(formatDate('2026-03-04T23:30:00Z')).toBe(formatDate('2026-03-04'))
    expect(formatDate('2026-03-04T00:30:00+05:00')).toBe(formatDate('2026-03-04'))
  })

  it('reads a plain date as a calendar date, not as UTC midnight', () => {
    viewerIn('America/Los_Angeles')

    expect(formatDate('2026-03-04')).toBe(formatted(new Date(2026, 2, 4)))
  })

  it('renders the same plain date east of Greenwich', () => {
    viewerIn('Asia/Dubai')

    expect(formatDate('2026-03-04')).toBe(formatted(new Date(2026, 2, 4)))
  })
})

describe('formatInstantAsDate', () => {
  it('converts an instant to the viewer day east of Greenwich', () => {
    viewerIn('Asia/Dubai')

    expect(formatInstantAsDate('2026-09-11T21:00:00Z')).toBe(formatted(new Date(2026, 8, 12)))
  })

  it('converts an instant to the viewer day west of Greenwich', () => {
    viewerIn('America/Los_Angeles')

    expect(formatInstantAsDate('2026-09-12T02:00:00Z')).toBe(formatted(new Date(2026, 8, 11)))
  })

  it('takes the same options as the other formatters', () => {
    viewerIn('Asia/Dubai')

    const options = { day: 'numeric', month: 'long' } as const

    expect(formatInstantAsDate('2026-09-11T21:00:00Z', options)).toBe(
      formatted(new Date(2026, 8, 12), options),
    )
  })
})

describe('formatDateTime', () => {
  it('renders an instant in the zone the reader is in', () => {
    expect(formatDateTime('2026-03-04T14:30:00Z')).toBe('Mar 4, 2026, 02:30 PM')
  })

  it('carries the offset the timestamp was written with', () => {
    expect(formatDateTime('2026-03-04T14:30:00+02:00')).toBe('Mar 4, 2026, 12:30 PM')
  })

  it('converts an instant to the viewer timezone', () => {
    viewerIn('Asia/Dubai')

    expect(formatDateTime('2026-09-11T21:00:00Z')).toBe(
      formatted(new Date(2026, 8, 12, 1, 0), {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }),
    )
  })
})
