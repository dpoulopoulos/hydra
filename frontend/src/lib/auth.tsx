import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { loginLoginAccessToken, usersGetUserMe } from '@/api'
import { errorMessage, readToken, setUnauthenticatedHandler, writeToken } from '@/lib/api'
import { AuthContext, type AuthValue } from '@/lib/auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readToken())
  const queryClient = useQueryClient()

  const signOut = useCallback(() => {
    writeToken(null)
    setToken(null)
    // Drop every cached answer: the next person to sign in must not see the
    // previous household's money.
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    setUnauthenticatedHandler(signOut)
    return () => setUnauthenticatedHandler(null)
  }, [signOut])

  const { data: user, isPending } = useQuery({
    queryKey: ['currentUser', token],
    queryFn: async () => {
      const { data, error } = await usersGetUserMe()
      if (error) throw error
      return data ?? null
    },
    enabled: token !== null,
    retry: false,
    staleTime: 5 * 60_000,
  })

  const signIn = useCallback(async (email: string, password: string) => {
    const { data, error } = await loginLoginAccessToken({
      body: { username: email, password },
    })
    if (error) throw new Error(errorMessage(error, 'Could not sign in. Check your details.'))
    if (!data) throw new Error('Could not sign in. Try again.')

    writeToken(data.access_token)
    setToken(data.access_token)
  }, [])

  const value = useMemo<AuthValue>(
    () => ({
      user: user ?? null,
      isLoading: token !== null && isPending,
      isAuthenticated: token !== null && Boolean(user),
      signIn,
      signOut,
    }),
    [user, token, isPending, signIn, signOut],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
