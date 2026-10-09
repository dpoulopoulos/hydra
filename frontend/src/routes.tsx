import { createBrowserRouter, Navigate, type RouteObject } from 'react-router'

import { AppShell } from '@/components/layout/app-shell'
import { RedirectIfSignedIn, RequireAuth } from '@/components/require-auth'
import { NotFoundPage } from '@/pages/not-found'

/** Screens for a visitor who is not signed in, and only for one. */
const signedOutRoutes: RouteObject[] = [
  { path: '/login', lazy: () => import('@/pages/auth/login') },
  { path: '/signup', lazy: () => import('@/pages/auth/signup') },
]

/**
 * Screens about a password.
 *
 * Signed out, like the two above, but they need no session to do their work,
 * and the reset link carries its token in the URL. A session check that merely
 * failed is not a reason to take someone off them.
 */
const passwordRoutes: RouteObject[] = [
  { path: '/forgot-password', lazy: () => import('@/pages/auth/forgot-password') },
  { path: '/reset-password', lazy: () => import('@/pages/auth/reset-password') },
]

/**
 * Screens reachable either way.
 *
 * Both arrive as a link in an email, which the recipient may open while
 * already signed in or before they have an account at all.
 */
const openRoutes: RouteObject[] = [
  { path: '/verify-email', lazy: () => import('@/pages/auth/verify-email') },
  { path: '/join-household', lazy: () => import('@/pages/auth/join-household') },
]

/** Screens inside the signed-in shell. */
const appRoutes: RouteObject[] = [
  { index: true, lazy: () => import('@/pages/dashboard') },
  { path: '/transactions', lazy: () => import('@/pages/transactions') },
  { path: '/accounts', lazy: () => import('@/pages/accounts') },
  { path: '/clients', lazy: () => import('@/pages/clients') },
  // The screen's old address, for bookmarks made before it was renamed.
  { path: '/income', element: <Navigate to="/clients" replace /> },
  { path: '/budgets', lazy: () => import('@/pages/budgets') },
  { path: '/goals', lazy: () => import('@/pages/goals') },
  { path: '/investments', lazy: () => import('@/pages/investments') },
  { path: '/recurring', lazy: () => import('@/pages/recurring') },
  { path: '/categories', lazy: () => import('@/pages/categories') },
  { path: '/reports', lazy: () => import('@/pages/reports') },
  { path: '/settings', lazy: () => import('@/pages/settings/household') },
  { path: '/settings/household', lazy: () => import('@/pages/settings/household') },
  { path: '/settings/profile', lazy: () => import('@/pages/settings/profile') },
  { path: '/settings/api-tokens', lazy: () => import('@/pages/settings/api-tokens') },
  { path: '/settings/bank', lazy: () => import('@/pages/settings/bank') },
  { path: '/settings/users', lazy: () => import('@/pages/settings/users') },
]

export const router = createBrowserRouter([
  { element: <RedirectIfSignedIn orInDoubt />, children: signedOutRoutes },
  { element: <RedirectIfSignedIn />, children: passwordRoutes },
  ...openRoutes,
  {
    element: <RequireAuth />,
    children: [{ element: <AppShell />, children: appRoutes }],
  },
  { path: '*', element: <NotFoundPage /> },
])
