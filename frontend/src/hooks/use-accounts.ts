import { useQuery } from '@tanstack/react-query'

import { accountsListAccounts } from '@/api'

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
