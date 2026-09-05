import { useQuery } from '@tanstack/react-query'

import { householdsGetHouseholdMe, householdsListHouseholdMembers, HouseholdRole } from '@/api'
import { useAuth } from '@/hooks/use-auth'

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

/**
 * Whether the signed-in member owns the household.
 *
 * Only an owner may change the household itself; everyone in it shares the
 * money. Pages use this to leave out a control the API would answer with a
 * 403, which is a better answer than letting somebody fill a field in and
 * then refusing it.
 */
export function useIsHouseholdOwner(): boolean {
  const { user } = useAuth()
  const members = useQuery({
    queryKey: ['household', 'members'],
    queryFn: async () => {
      const { data, error } = await householdsListHouseholdMembers()
      if (error) throw error
      return data
    },
    staleTime: 5 * 60_000,
  })

  return (
    members.data?.data.find((member) => member.user_id === user?.id)?.role === HouseholdRole.OWNER
  )
}
