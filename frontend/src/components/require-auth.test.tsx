import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { RedirectIfSignedIn, RequireAuth } from '@/components/require-auth'
import { useAuth } from '@/hooks/use-auth'
import type { AuthValue } from '@/lib/auth-context'
import { session } from '@/test/auth'

// Both gates read the session the provider worked out and route on it. The
// tests hand them a session directly.
vi.mock('@/hooks/use-auth', () => ({ useAuth: vi.fn() }))

function renderGate(value: AuthValue) {
  vi.mocked(useAuth).mockReturnValue(value)
  return render(
    <MemoryRouter initialEntries={['/budgets']}>
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/budgets" element={<p>Budgets</p>} />
        </Route>
        <Route path="/login" element={<p>Sign in</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the gate on the signed-in part of the app', () => {
  it('shows the page to someone who is signed in', () => {
    renderGate(session({ isAuthenticated: true }))

    expect(screen.getByText('Budgets')).toBeInTheDocument()
  })

  it('sends someone whose session is over to the sign-in screen', () => {
    renderGate(session({ isUnauthenticated: true }))

    expect(screen.getByText('Sign in')).toBeInTheDocument()
  })

  it('keeps the page on screen when a background check failed', () => {
    renderGate(session({ isAuthenticated: true, error: { status: 502 } }))

    expect(screen.getByText('Budgets')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('offers a way out of a failure that will not clear', async () => {
    const signOut = vi.fn()
    renderGate(session({ error: { status: 502 }, signOut }))

    await userEvent.click(screen.getByRole('button', { name: /sign out/i }))
    expect(signOut).toHaveBeenCalledOnce()
  })

  it('reports a check that could not be made, and offers another go', async () => {
    const retry = vi.fn()
    renderGate(session({ error: { status: 502 }, retry }))

    expect(screen.queryByText('Sign in')).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))
    expect(retry).toHaveBeenCalledOnce()
  })

  it('shows that another go is under way', () => {
    renderGate(session({ error: { status: 502 }, isRetrying: true }))

    const again = screen.getByRole('button', { name: /try again/i })
    expect(again).toBeDisabled()
  })

  it('waits while the token is being checked', () => {
    renderGate(session({ isLoading: true }))

    expect(screen.queryByText('Sign in')).not.toBeInTheDocument()
    expect(screen.getByText('Loading')).toBeInTheDocument()
  })
})

function renderSignedOutGate(value: AuthValue, entry = '/login') {
  vi.mocked(useAuth).mockReturnValue(value)
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route element={<RedirectIfSignedIn />}>
          <Route path="/login" element={<p>Sign in</p>} />
          <Route path="/reset-password" element={<p>Choose a new password</p>} />
        </Route>
        <Route path="/" element={<p>Home</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('the gate on the signed-out part of the app', () => {
  it('shows the sign-in screen to someone whose session is over', () => {
    renderSignedOutGate(session({ isUnauthenticated: true }))

    expect(screen.getByText('Sign in')).toBeInTheDocument()
  })

  it('sends a signed-in person to the app', () => {
    renderSignedOutGate(session({ isAuthenticated: true }))

    expect(screen.getByText('Home')).toBeInTheDocument()
  })

  it('does not show the sign-in screen when the check merely failed', () => {
    renderSignedOutGate(session({ error: { status: 502 } }))

    expect(screen.queryByText('Sign in')).not.toBeInTheDocument()
    expect(screen.getByText('Home')).toBeInTheDocument()
  })

  it('still shows a password reset when the check failed', () => {
    // The reset token is in the URL, and the page needs no session anyway.
    renderSignedOutGate(session({ error: { status: 502 } }), '/reset-password')

    expect(screen.getByText('Choose a new password')).toBeInTheDocument()
  })
})
