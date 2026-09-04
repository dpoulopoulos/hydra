import { afterEach, beforeEach, vi } from 'vitest'

const RealNumberFormat = Intl.NumberFormat

/**
 * Read and write numbers as one locale for the rest of the file.
 *
 * The suite already pins the fallback locale to en-US in `src/test/setup.ts`,
 * so a test that formats or reads an amount without naming one means the same
 * thing on every machine. This is for the few files that need a *different*
 * default: reading an amount out of a field is only wrong in a locale that
 * groups with a dot, so those tests have to run as such a reader.
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
      return new RealNumberFormat(asked ?? locale, options)
    } as unknown as typeof Intl.NumberFormat)
  })

  // Restored by hand rather than with `restoreAllMocks`, so a file that spies
  // on something else of its own keeps it.
  afterEach(() => {
    vi.mocked(Intl.NumberFormat).mockRestore()
  })
}
