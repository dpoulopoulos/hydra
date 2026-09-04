import { useQuery } from '@tanstack/react-query'

import { householdsGetHouseholdMe } from '@/api'

/**
 * The current household.
 *
 * Every page needs its currency to render money, so this is cached for the
 * session rather than fetched per screen.
 */
export function useHousehold() {
  return useQuery({
    queryKey: ['household'],
    queryFn: async () => {
      const { data, error } = await householdsGetHouseholdMe()
      if (error) throw error
      return data
    },
    staleTime: 5 * 60_000,
  })
}

/** The household's currency code, defaulting to EUR until it has loaded. */
export function useCurrency(): string {
  const { data } = useHousehold()
  return data?.currency_code ?? 'EUR'
}
