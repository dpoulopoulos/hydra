import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { Component as Login } from '@/pages/auth/login'

const signIn = vi.fn()

vi.mock('@/hooks/use-auth', () => ({ useAuth: () => ({ signIn }) }))

/** Where the router ended up, path and query string together. */
function Landed() {
  const location = useLocation()
  return <p>landed on {`${location.pathname}${location.search}`}</p>
}

function renderLogin(from?: { pathname: string; search?: string }) {
  render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state: from ? { from } : null }]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  )
}

async function signInAs() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@example.com')
  await user.type(screen.getByLabelText('Password'), 'secret')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('signing in', () => {
  it('goes back to the page the gate sent them from, query string and all', async () => {
    // A bank login comes back with its code in the query string. A session
    // that ran out meanwhile must not cost the connection.
    renderLogin({ pathname: '/settings/bank/callback', search: '?code=c&state=s' })

    await signInAs()

    expect(
      await screen.findByText('landed on /settings/bank/callback?code=c&state=s'),
    ).toBeInTheDocument()
  })

  it('goes to the dashboard when nothing sent them', async () => {
    renderLogin()

    await signInAs()

    expect(await screen.findByText('landed on /')).toBeInTheDocument()
  })
})
