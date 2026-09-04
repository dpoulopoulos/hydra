import { use } from 'react'

import { AuthContext, type AuthValue } from '@/lib/auth-context'

/** The signed-in user, and the two actions that change who that is. */
export function useAuth(): AuthValue {
  const value = use(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
