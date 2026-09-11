/**
 * Helpers for the tests that read formatted numbers and dates.
 *
 * `Intl.NumberFormat` and `Intl.DateTimeFormat` fall back to the locale of the
 * machine they run on when the caller names none, and the app calls both that
 * way on purpose: a screen should read the way its reader's system does. A
 * test that asserts "€1,200.50" is then asserting the tester's locale, and the
 * same code fails on a machine set to de-DE. Pinning the fallback makes the
 * locale a test formats in part of the test rather than part of the machine.
 *
 * Only the fallback moves. A caller that names a locale still gets it, so a
 * test can be about a particular locale by asking for it.
 */

import { afterEach, beforeEach, vi } from 'vitest'

type Formatter = typeof Intl.NumberFormat | typeof Intl.DateTimeFormat

/** The unpinned formatters, so pinning twice replaces rather than nests. */
const original = {
  NumberFormat: Intl.NumberFormat,
  DateTimeFormat: Intl.DateTimeFormat,
}

function withDefaultLocale<T extends Formatter>(Formatter: T, locale: string): T {
  return new Proxy(Formatter, {
    construct(target, [locales, options]: [Intl.LocalesArgument, unknown], newTarget) {
      return Reflect.construct(target, [locales ?? locale, options], newTarget)
    },
    apply(target, thisArg, [locales, options]: [Intl.LocalesArgument, unknown]) {
      return Reflect.apply(target, thisArg, [locales ?? locale, options])
    },
  })
}

/**
 * Make `locale` the one an unnamed `Intl` formatter uses for the current test
 * file, whatever locale the machine running it defaults to.
 *
 * `src/test/setup.ts` calls this with en-US for the whole suite, so most files
 * need nothing; a file that is about another locale can call it with its own.
 */
export function pinLocale(locale: string): void {
  Intl.NumberFormat = withDefaultLocale(original.NumberFormat, locale)
  Intl.DateTimeFormat = withDefaultLocale(original.DateTimeFormat, locale)
}

/**
 * Read and write numbers as one locale for the rest of the file.
 *
 * A narrower `pinLocale` for the few files that need a different default for
 * numbers alone, undone again after every test: reading an amount out of a
 * field is only wrong in a locale that groups with a dot, so those tests have
 * to run as such a reader without moving the dates along with them.
 *
 * A locale asked for explicitly is still honoured; one left out resolves to
 * `locale` rather than to the suite's en-US.
 */
export function pinNumberLocale(locale: string) {
  beforeEach(() => {
    vi.spyOn(Intl, 'NumberFormat').mockImplementation(function (
      asked?: Intl.LocalesArgument,
      options?: Intl.NumberFormatOptions,
    ) {
      return new original.NumberFormat(asked ?? locale, options)
    } as unknown as typeof Intl.NumberFormat)
  })

  // Restored by hand rather than with `restoreAllMocks`, so a file that spies
  // on something else of its own keeps it.
  afterEach(() => {
    vi.mocked(Intl.NumberFormat).mockRestore()
  })
}
