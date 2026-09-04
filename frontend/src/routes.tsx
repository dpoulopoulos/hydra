import { createBrowserRouter } from 'react-router'

import { AppShell } from '@/components/layout/app-shell'
import { RedirectIfSignedIn, RequireAuth } from '@/components/require-auth'
import { NotFoundPage } from '@/pages/not-found'

export const router = createBrowserRouter([
  {
    element: <RedirectIfSignedIn />,
    children: [
      { path: '/login', lazy: () => import('@/pages/auth/login') },
      { path: '/signup', lazy: () => import('@/pages/auth/signup') },
      { path: '/forgot-password', lazy: () => import('@/pages/auth/forgot-password') },
      { path: '/reset-password', lazy: () => import('@/pages/auth/reset-password') },
    ],
  },
  // Reachable signed in or out: the link arrives by email either way.
  { path: '/verify-email', lazy: () => import('@/pages/auth/verify-email') },
  { path: '/join-household', lazy: () => import('@/pages/auth/join-household') },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [{ index: true, lazy: () => import('@/pages/dashboard') }],
      },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
])
