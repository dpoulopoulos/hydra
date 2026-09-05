import { useQuery } from '@tanstack/react-query'

import { investmentsListInstruments } from '@/api'

/** The instruments the household tracks, for pickers and for the trade form. */
export function useInstruments() {
  return useQuery({
    queryKey: ['instruments'],
    queryFn: async () => {
      const { data, error } = await investmentsListInstruments({ query: { limit: 200 } })
      if (error) throw error
      return data
    },
    staleTime: 60_000,
  })
}
