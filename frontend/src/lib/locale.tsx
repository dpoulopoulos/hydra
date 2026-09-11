import type { ReactNode } from 'react'

import { useHousehold } from '@/hooks/use-household'
import { LocaleContext } from '@/lib/locale-context'

/**
 * Write every amount below this the way the household writes numbers.
 *
 * A household picks one locale for everyone in it, so two people sharing the
 * same budget are shown the same figures whatever their browsers are set to,
 * and each of them can type an amount back the way they were shown it. A
 * household that has named none is left with what it always had: each reader's
 * own browser.
 */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const { data } = useHousehold()

  return <LocaleContext value={data?.locale ?? undefined}>{children}</LocaleContext>
}
