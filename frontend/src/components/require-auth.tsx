import { Loader2 } from 'lucide-react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from '@/hooks/use-auth'

/** Gate for the signed-in part of the app. */
export function RequireAuth() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex min-h-svh items-center justify-center">
        <Loader2 className="text-muted-foreground size-5 animate-spin" />
        <span className="sr-only">Loading</span>
      </div>
    )
  }

  // Remember where they were headed, so signing in lands them there.
  if (!isAuthenticated) return <Navigate to="/login" state={{ from: location }} replace />

  return <Outlet />
}

/** Keeps a signed-in person out of the sign-in and sign-up screens. */
export function RedirectIfSignedIn() {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) return null
  if (isAuthenticated) return <Navigate to="/" replace />

  return <Outlet />
}
