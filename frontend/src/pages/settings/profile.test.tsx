import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { UserPublic } from '@/api'
import { Component as ProfilePage } from '@/pages/settings/profile'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    usersUpdateUserMe: vi.fn(),
    usersUpdatePasswordMe: vi.fn(),
    usersDeleteUserMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const user: UserPublic = {
  id: 'u1',
  email: 'proven@example.com',
  full_name: 'Ada',
  is_active: true,
  is_superuser: false,
  created_at: '2026-01-01T00:00:00Z',
}

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user, signOut: vi.fn() }),
}))

const api = await import('@/api')
const { toast } = await import('sonner')

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ProfilePage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('profile details', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.usersUpdateUserMe).mockResolvedValue({ data: user } as never)
  })

  it('confirms a saved name plainly', async () => {
    renderPage()
    const person = userEvent.setup()

    await person.clear(screen.getByLabelText('Name'))
    await person.type(screen.getByLabelText('Name'), 'Ada L')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Profile saved'))
  })

  it('says a new address is not the account’s until it is confirmed', async () => {
    renderPage()
    const person = userEvent.setup()

    await person.clear(screen.getByLabelText('Email'))
    await person.type(screen.getByLabelText('Email'), 'moving-to@example.com')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('moving-to@example.com')),
    )
    expect(toast.success).not.toHaveBeenCalledWith('Profile saved')
  })

  it('puts the current address back in the form while the new one is pending', async () => {
    renderPage()
    const person = userEvent.setup()

    await person.clear(screen.getByLabelText('Email'))
    await person.type(screen.getByLabelText('Email'), 'moving-to@example.com')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    // The account still holds the address it has proven, and the form is what
    // says which one that is.
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveValue('proven@example.com'))
  })
})
