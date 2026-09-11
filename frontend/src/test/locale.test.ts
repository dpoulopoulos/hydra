import { afterEach, describe, expect, it } from 'vitest'

import { pinLocale } from '@/test/locale'

const NumberFormat = Intl.NumberFormat
const DateTimeFormat = Intl.DateTimeFormat

afterEach(() => {
  Intl.NumberFormat = NumberFormat
  Intl.DateTimeFormat = DateTimeFormat
})

describe('pinLocale', () => {
  it('formats a number in the pinned locale when none is named', () => {
    pinLocale('de-DE')

    expect(new Intl.NumberFormat().format(1200.5)).toBe('1.200,5')
  })

  it('formats a date in the pinned locale when none is named', () => {
    pinLocale('de-DE')

    expect(
      new Intl.DateTimeFormat(undefined, { timeZone: 'UTC' }).format(Date.UTC(2026, 0, 31)),
    ).toBe('31.1.2026')
  })

  it('still honours a locale the caller names', () => {
    pinLocale('de-DE')

    expect(new Intl.NumberFormat('en-US').format(1200.5)).toBe('1,200.5')
    expect(
      new Intl.DateTimeFormat('en-US', { timeZone: 'UTC' }).format(Date.UTC(2026, 0, 31)),
    ).toBe('1/31/2026')
  })

  it('keeps the formatters usable as formatters', () => {
    pinLocale('de-DE')

    const format = new Intl.NumberFormat(undefined, { style: 'currency', currency: 'EUR' })

    expect(format).toBeInstanceOf(Intl.NumberFormat)
    expect(format.resolvedOptions().locale).toBe('de-DE')
    expect(Intl.NumberFormat.supportedLocalesOf(['en-US'])).toEqual(['en-US'])
  })

  it('pins a locale once, however many times it is asked for', () => {
    pinLocale('de-DE')
    pinLocale('en-US')

    expect(new Intl.NumberFormat().format(1200.5)).toBe('1,200.5')
  })
})
