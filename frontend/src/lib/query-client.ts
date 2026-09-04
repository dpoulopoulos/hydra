import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Money data changes when someone in the household edits it, so refetch
      // on focus, but not so eagerly that switching tabs floods the API.
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // Retrying a 4xx just repeats the same rejection.
        const status = (error as { status?: number }).status
        if (status && status >= 400 && status < 500) return false
        return failureCount < 2
      },
    },
  },
})
