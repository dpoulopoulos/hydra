import { QueryClient } from '@tanstack/react-query'

import { isRejection } from '@/lib/api'

/**
 * Whether a failed request is worth trying again.
 *
 * A rejection is the server's considered answer, so repeating the request only
 * repeats it. Anything else may well pass a second later, so give it two more
 * goes before settling for the failure.
 */
export function retryUnlessRejected(failureCount: number, error: unknown): boolean {
  if (isRejection(error)) return false
  return failureCount < 2
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Money data changes when someone in the household edits it, so refetch
      // on focus, but not so eagerly that switching tabs floods the API.
      staleTime: 30_000,
      retry: retryUnlessRejected,
    },
  },
})
