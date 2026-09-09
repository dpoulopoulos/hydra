import { useQuery } from '@tanstack/react-query'

import { accountsListAccounts } from '@/api'
import { useCurrency } from '@/hooks/use-household'

/** The household's accounts, for pickers and for the accounts page. */
export function useAccounts(options?: { includeArchived?: boolean }) {
  return useQuery({
    queryKey: ['accounts', { includeArchived: options?.includeArchived ?? false }],
    queryFn: async () => {
      const { data, error } = await accountsListAccounts({
        query: { include_archived: options?.includeArchived ?? false, limit: 200 },
      })
      if (error) throw error
      return data
    },
    staleTime: 60_000,
  })
}

/**
 * Reads the currency an account keeps its money in.
 *
 * An amount belongs to the account it sits in, and that is where the currency
 * is recorded, so a form that asks for one reads it from there rather than
 * from the household. The household's currency is the fallback: it is what a
 * new account is opened in, and the answer would be the same anyway while the
 * account list is still on its way.
 *
 * A reader rather than the currency itself, because one form can hold several
 * accounts at once: the one a picker shows, the one the record being edited
 * hangs off, the one a submitted set of values names.
 *
 * Archived accounts are read too. Archiving an account stops it taking
 * anything new; it does not change the currency of what it already holds, and
 * a record on one is still shown and edited. Leaving them out would answer the
 * household's currency for such a record and show its amount in the wrong one.
 */
export function useAccountCurrency(): (accountId: string | null | undefined) => string {
  const householdCurrency = useCurrency()
  const { data } = useAccounts({ includeArchived: true })

  return (accountId) =>
    (accountId ? data?.data.find((account) => account.id === accountId)?.currency_code : null) ??
    householdCurrency
}
