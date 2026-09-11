import { createContext, useContext } from 'react'

/**
 * The locale every amount on the screen is written and read in.
 *
 * `undefined` means no household has said, and each reader's browser decides
 * for them, which is what `Intl` does when a caller names no locale. Split
 * from the provider so the module that exports the component exports nothing
 * else, which is what fast refresh needs.
 */
export const LocaleContext = createContext<string | undefined>(undefined)

/**
 * The locale to render and read amounts in.
 *
 * Every money surface passes what this returns to the helpers in `@/lib/money`
 * and to `amountSchema`, so what a household is shown and what it may type
 * back are the same two characters. A screen outside the provider, such as
 * signing in, gets `undefined` and formats the reader's own way.
 */
export function useLocale(): string | undefined {
  return useContext(LocaleContext)
}
