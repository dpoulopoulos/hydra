import { useQuery } from '@tanstack/react-query'

import {
  bankGetBankStatus,
  bankListBankConnections,
  bankListBankInbox,
  BankReviewStatus,
} from '@/api'

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

/**
 * How many bank rows wait for review, for the badge in the sidebar.
 *
 * One row is asked for, since only the count is wanted.
 */
export function usePendingBankCount(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['bank', 'inbox', 'count'],
    enabled: options?.enabled ?? true,
    queryFn: async () => {
      const { data, error } = await bankListBankInbox({
        query: { status: BankReviewStatus.PENDING, limit: 1 },
      })
      if (error || !data) throw error ?? new Error('Could not count the inbox.')
      return data.count
    },
    staleTime: 60_000,
  })
}
