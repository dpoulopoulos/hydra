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
    ],
  },
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
