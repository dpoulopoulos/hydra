import { describe, expect, it } from 'vitest'

import { RecurrenceFrequency } from '@/api'
import { describeCadence, presetOf } from '@/lib/cadence'

describe('describeCadence', () => {
  it('names the days when a client is seen on several', () => {
    // The case one appointment a week cannot express.
    expect(describeCadence(RecurrenceFrequency.WEEKLY, 1, '2026-06-01', [0, 1, 3, 4])).toMatch(
      /^Every week on .+,.+,.+,/,
    )
  })

  it('falls back to the weekday it was pinned to', () => {
    expect(describeCadence(RecurrenceFrequency.WEEKLY, 1, '2026-06-01', [])).toMatch(
      /^Every week on \w+$/,
    )
  })

  it('says a fortnight as a fortnight', () => {
    expect(describeCadence(RecurrenceFrequency.WEEKLY, 2, '2026-06-03', [])).toMatch(
      /^Every 2 weeks on \w+$/,
    )
  })

  it('keeps a monthly day of the month', () => {
    expect(describeCadence(RecurrenceFrequency.MONTHLY, 1, '2026-03-10', [])).toBe(
      'Every month on the 10',
    )
  })

  it('says every day', () => {
    expect(describeCadence(RecurrenceFrequency.DAILY, 1, '2026-03-10', [])).toBe('Every day')
  })

  it('has words for somebody with no pattern', () => {
    expect(describeCadence(null, 1, null, [])).toBe('As and when')
  })
})

describe('presetOf', () => {
  it('matches a stored pattern back to the option that made it', () => {
    expect(presetOf(RecurrenceFrequency.WEEKLY, 2)).toBe('fortnightly')
  })

  it('reads no pattern as the ad-hoc option', () => {
    expect(presetOf(null, 1)).toBe('ad-hoc')
  })
})
