import { Loader2 } from 'lucide-react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { ErrorState } from '@/components/data-state'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/use-auth'

/** Gate for the signed-in part of the app. */
export function RequireAuth() {
  const { isAuthenticated, isUnauthenticated, isLoading, error, retry, isRetrying, signOut } =
    useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        <Loader2 className="text-muted-foreground size-5 animate-spin" />
        <span className="sr-only">Loading</span>
      </div>
    )
  }

  // A user we already have is a session we already know about. A refetch that
  // failed in the background — the tab regaining focus while the backend
  // restarts — says nothing about it, so leave the page where it was.
  if (isAuthenticated) return <Outlet />

  // With nothing to show, a check that failed for a reason the server did not
  // choose still says nothing about the session. Say what happened and offer
  // another go, rather than the sign-in form to someone who never signed out.
  // Signing out is the way past a failure that will not clear.
  if (error && !isUnauthenticated) {
    return (
      <div className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center gap-4 p-6">
        <ErrorState error={error} title="Could not check your session" />
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={retry} disabled={isRetrying}>
            {isRetrying ? <Loader2 className="size-4 animate-spin" /> : null}
            Try again
          </Button>
          <Button variant="ghost" onClick={signOut}>
            Sign out
          </Button>
        </div>
      </div>
    )
  }

  // Remember where they were headed, so signing in lands them there.
  return <Navigate to="/login" state={{ from: location }} replace />
}

/**
 * Keeps a signed-in person out of a screen meant for a signed-out one.
 *
 * `orInDoubt` marks the screens a session in doubt is worth taking someone off
 * as well: the sign-in and sign-up forms, which have nothing to say to someone
 * who never signed out. The rest — a forgotten password, a password reset —
 * need no session at all, and a reset link carries its token in the URL, which
 * a redirect would throw away. Which screen is which is a question the route
 * tree already answers, so it is asked there rather than guessed from the URL:
 * the router reaches the same screen from `/login`, `/Login` and `/login/`.
 */
export function RedirectIfSignedIn({ orInDoubt = false }: { orInDoubt?: boolean }) {
  const { isAuthenticated, isUnauthenticated, isLoading, error } = useAuth()

  if (isLoading) return null
  if (isAuthenticated) return <Navigate to="/" replace />

  // A check that failed is not a session that ended, so it does not earn the
  // sign-in form either. The gate on the app owns that case, where it can be
  // reported and retried; send them there and let it do the talking.
  if (orInDoubt && error && !isUnauthenticated) return <Navigate to="/" replace />

  return <Outlet />
}
