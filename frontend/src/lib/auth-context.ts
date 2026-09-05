import { createContext } from 'react'

import type { UserPublic } from '@/api'

export type AuthValue = {
  user: UserPublic | null
  /** True until the stored token has been checked against the API. */
  isLoading: boolean
  isAuthenticated: boolean
  /** True only when the session is over: no token, or the API rejected it. */
  isUnauthenticated: boolean
  /** Set when the check failed for a reason that is not a rejection. */
  error: unknown
  /** Ask again, after a failure that may well have passed by now. */
  retry: () => void
  /** True while a repeat check is in flight, so the retry can show its work. */
  isRetrying: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

// Split from the provider so the module that exports the component exports
// nothing else, which is what fast refresh needs.
export const AuthContext = createContext<AuthValue | null>(null)
