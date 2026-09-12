import { useQuery } from '@tanstack/react-query'

import { budgetsListBudgets } from '@/api'

/**
 * The limits one month has set.
 *
 * Keyed by the month alone, so everything asking for a month shares the one
 * cached answer, and the `['budgets']` invalidation every write already fires
 * clears each of them.
 */
export function useMonthBudgets(month: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['budgets', month],
    queryFn: async () => {
      const { data, error } = await budgetsListBudgets({ query: { month } })
      if (error) throw error
      return data
    },
    enabled: options?.enabled ?? true,
  })
}
