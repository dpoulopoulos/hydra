import { useQuery } from '@tanstack/react-query'

import { bankGetBankStatus, bankListBankConnections } from '@/api'

/**
 * Whether this server can connect a bank at all.
 *
 * It is off until whoever runs hydra registers it with the bank provider, so
 * the screens that need it ask first rather than offering a button that only
 * fails.
 */
export function useBankStatus() {
  return useQuery({
    queryKey: ['bank', 'status'],
    queryFn: async () => {
      const { data, error } = await bankGetBankStatus()
      if (error || !data) throw error ?? new Error('Could not check bank sync.')
      return data
    },
    staleTime: 30 * 60_000,
  })
}

/** The household's connected banks, each with the accounts its login reached. */
export function useBankConnections(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['bank', 'connections'],
    enabled: options?.enabled ?? true,
    queryFn: async () => {
      const { data, error } = await bankListBankConnections()
      if (error || !data) throw error ?? new Error('Could not load your banks.')
      return data
    },
  })
}
