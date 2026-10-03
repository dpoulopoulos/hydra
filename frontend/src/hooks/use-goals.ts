import { useQuery } from '@tanstack/react-query'

import { goalsListGoals } from '@/api'

/** The household's savings goals, with how each savings account splits across them. */
export function useGoals(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['goals'],
    enabled: options?.enabled ?? true,
    queryFn: async () => {
      const { data, error } = await goalsListGoals()
      // The endpoint declares no error body, so the client cannot tell the
      // type checker that no error means data. Checked here, once, so every
      // reader can rely on it.
      if (error || !data) throw error ?? new Error('The goals could not be loaded.')
      return data
    },
  })
}
