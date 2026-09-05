import { useCallback, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { loginLoginAccessToken, usersGetUserMe } from '@/api'
import {
  errorMessage,
  isRejection,
  readToken,
  setUnauthenticatedHandler,
  writeToken,
} from '@/lib/api'
import { AuthContext, type AuthValue } from '@/lib/auth-context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => readToken())
  // What the session check last ran into, kept because the query does not:
  // see below, where it is worked out.
  const [lastFailure, setLastFailure] = useState<unknown>(null)
  const queryClient = useQueryClient()

  const signOut = useCallback(() => {
    writeToken(null)
    setToken(null)
    setLastFailure(null)
    // Drop every cached answer: the next person to sign in must not see the
    // previous household's money.
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    setUnauthenticatedHandler(signOut)
    return () => setUnauthenticatedHandler(null)
  }, [signOut])

  // No retry policy of its own: the shared one already declines to repeat a
  // rejected token and does try again through a backend that is restarting,
  // which is exactly the difference this query turns into an auth decision.
  const {
    data: user,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['currentUser', token],
    queryFn: async () => {
      const { data, error } = await usersGetUserMe()
      if (error) throw error
      return data ?? null
    },
    enabled: token !== null,
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
    // A new token is a new question; what the last one ran into says nothing
    // about it.
    setLastFailure(null)
  }, [])

  // Only an answer from the server ends a session. A 4xx is that answer — the
  // token refused, the account no longer active, the record gone — and none of
  // them clears by asking again. A request that never got an answer says
  // nothing about a token that is still in storage and still good, so it is
  // reported as a failure to retry rather than a sign-out.
  const rejected = isError && isRejection(error)

  // Asking a check that never succeeded again starts the query over:
  // react-query drops the error and the status goes back to pending, whether
  // the repeat came from the retry button or from the tab regaining focus.
  // What failed is remembered across the wait, so the screen reporting it
  // stays where it is instead of being replaced by a full-page spinner.
  const checkFailed = isError ? error : isPending ? lastFailure : null
  if (checkFailed !== lastFailure) setLastFailure(checkFailed)

  // A rejection is not a failure to report: it is a session that has ended,
  // and the sign-in screen is the answer to it.
  const failure = rejected ? null : checkFailed

  const retry = useCallback(() => {
    void refetch()
  }, [refetch])

  const value = useMemo<AuthValue>(
    () => ({
      user: user ?? null,
      // Only the first check holds up the app. Once one has failed there is
      // something to show, and the repeat says so on that screen rather than
      // sending the whole page back to a spinner.
      isLoading: token !== null && isPending && checkFailed === null,
      isAuthenticated: token !== null && Boolean(user),
      isUnauthenticated: token === null || rejected,
      error: failure,
      retry,
      isRetrying: isFetching && checkFailed !== null,
      signIn,
      signOut,
    }),
    [user, token, isPending, isFetching, rejected, failure, checkFailed, retry, signIn, signOut],
  )

  return <AuthContext value={value}>{children}</AuthContext>
}
