import { createContext } from 'react'

import type { UserPublic } from '@/api'

export type AuthValue = {
  user: UserPublic | null
  /** True until the stored token has been checked against the API. */
  isLoading: boolean
  isAuthenticated: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
}

// Split from the provider so the module that exports the component exports
// nothing else, which is what fast refresh needs.
export const AuthContext = createContext<AuthValue | null>(null)
