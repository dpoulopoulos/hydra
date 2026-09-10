import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { PendingEmailChange, UserPublic } from '@/api'
import { formatDateTime } from '@/lib/month'
import { Component as Profile } from '@/pages/settings/profile'

// `useAuth` reads the cached current user, which the page mirrors into its
// details form. The tests publish that user through a small store, so an
// answer arriving while someone is editing is a state they can produce.
const authStore = vi.hoisted(() => {
  let current: unknown = null
  const listeners = new Set<() => void>()
  return {
    read: () => current,
    publish(next: unknown) {
      current = next
      for (const listener of listeners) listener()
    },
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
})

vi.mock('@/hooks/use-auth', async () => {
  const { useSyncExternalStore } = await import('react')
  return {
    useAuth: () => {
      const user = useSyncExternalStore(authStore.subscribe, authStore.read) as UserPublic | null
      return {
        user,
        isLoading: false,
        isAuthenticated: Boolean(user),
        signIn: vi.fn(),
        signOut: vi.fn(),
      }
    },
  }
})

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    emailVerificationGetPendingEmailChangeMe: vi.fn(),
    usersUpdateUserMe: vi.fn(),
    usersUpdatePasswordMe: vi.fn(),
    usersDeleteUserMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const pendingChange: PendingEmailChange = {
  new_email: 'moving-to@example.com',
  expires_at: '2026-01-02T00:00:00Z',
}

const api = await import('@/api')
const { toast } = await import('sonner')

function user(overrides: Partial<UserPublic> = {}): UserPublic {
  return {
    id: 'u1',
    email: 'alex@example.com',
    full_name: 'Alex Rivera',
    is_active: true,
    is_superuser: false,
    household_id: 'h1',
    ...overrides,
  } as UserPublic
}

/** Renders the page and hands back a way to answer with a fresh user object. */
function renderProfile() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Profile />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { refetch: (next: UserPublic) => act(() => authStore.publish(next)) }
}

const nameField = () => screen.getByLabelText('Name')
const emailField = () => screen.getByLabelText('Email')

describe('profile page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.usersUpdateUserMe).mockResolvedValue({ data: user() } as never)
    vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
      data: null,
    } as never)
    authStore.publish(user())
  })

  it('shows the current details', () => {
    renderProfile()
    expect(nameField()).toHaveValue('Alex Rivera')
    expect(emailField()).toHaveValue('alex@example.com')
  })

  it('keeps an edit in progress when the user refetches', async () => {
    const person = userEvent.setup()
    const { refetch } = renderProfile()

    await person.clear(nameField())
    await person.type(nameField(), 'Alex R.')

    refetch(user({ full_name: 'Alexandra Rivera' }))

    expect(nameField()).toHaveValue('Alex R.')

    // What is on screen is what is saved: an answer arriving mid-edit must not
    // leave the form submitting something the field never showed.
    await person.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() => expect(api.usersUpdateUserMe).toHaveBeenCalled())
    expect(vi.mocked(api.usersUpdateUserMe).mock.calls[0][0]).toMatchObject({
      body: { full_name: 'Alex R.' },
    })
  })

  it('takes on the refetched details when nothing is being edited', async () => {
    const { refetch } = renderProfile()

    refetch(user({ full_name: 'Alexandra Rivera' }))

    await waitFor(() => expect(nameField()).toHaveValue('Alexandra Rivera'))
  })

  it('saves what was typed', async () => {
    const person = userEvent.setup()
    renderProfile()

    await person.clear(nameField())
    await person.type(nameField(), 'Alex R.')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    await waitFor(() => expect(api.usersUpdateUserMe).toHaveBeenCalled())
    expect(vi.mocked(api.usersUpdateUserMe).mock.calls[0][0]).toMatchObject({
      body: { full_name: 'Alex R.', email: 'alex@example.com' },
    })
  })

  it('still follows the server after a save of its own', async () => {
    const person = userEvent.setup()
    const { refetch } = renderProfile()

    await person.clear(nameField())
    await person.type(nameField(), 'Alex R.')
    await person.click(screen.getByRole('button', { name: 'Save details' }))
    await waitFor(() => expect(api.usersUpdateUserMe).toHaveBeenCalled())
    refetch(user({ full_name: 'Alex R.' }))

    // Saving is not editing: the form is level with the server again, so a
    // change made elsewhere afterwards still reaches it.
    refetch(user({ full_name: 'Alexandra Rivera' }))
    await waitFor(() => expect(nameField()).toHaveValue('Alexandra Rivera'))
  })

  it('confirms a saved name plainly', async () => {
    renderProfile()
    const person = userEvent.setup()

    await person.clear(nameField())
    await person.type(nameField(), 'Alex R.')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Profile saved'))
  })

  it('says a new address is not the account’s until it is confirmed', async () => {
    renderProfile()
    const person = userEvent.setup()

    await person.clear(emailField())
    await person.type(emailField(), 'moving-to@example.com')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('moving-to@example.com')),
    )
    expect(toast.success).not.toHaveBeenCalledWith('Profile saved')
  })

  it('puts the current address back in the form while the new one is pending', async () => {
    renderProfile()
    const person = userEvent.setup()

    await person.clear(emailField())
    await person.type(emailField(), 'moving-to@example.com')
    await person.click(screen.getByRole('button', { name: 'Save details' }))

    // The account still holds the address it has proven, and the form is what
    // says which one that is.
    await waitFor(() => expect(emailField()).toHaveValue('alex@example.com'))
  })
})

describe('a pending change of address', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
      data: pendingChange,
    } as never)
    authStore.publish(user())
  })

  it('says which address the account is waiting on', async () => {
    renderProfile()

    // The toast that said so is long gone by the time the page is reloaded.
    expect(await screen.findByRole('alert')).toHaveTextContent('moving-to@example.com')
  })

  it('says how long the link has left', async () => {
    renderProfile()

    // A change with a deadline nobody can see is one you cannot tell is still
    // worth waiting on.
    expect(await screen.findByRole('alert')).toHaveTextContent(
      formatDateTime(pendingChange.expires_at),
    )
  })

  it('says nothing when no change is outstanding', async () => {
    vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
      data: null,
    } as never)
    renderProfile()

    await waitFor(() => expect(api.emailVerificationGetPendingEmailChangeMe).toHaveBeenCalled())
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says when it could not find out whether a change is outstanding', async () => {
    // Staying quiet would be the same screen as no change at all, which tells
    // an account waiting on a link that it is waiting on nothing.
    vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
      error: { detail: 'Boom.', status: 500 },
    } as never)
    renderProfile()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not check for a pending email change',
    )
  })

  it('asks again when the failed lookup is retried', async () => {
    vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
      error: { detail: 'Boom.', status: 500 },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
      data: pendingChange,
    } as never)
    await person.click(await screen.findByRole('button', { name: 'Try again' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('moving-to@example.com')
  })
})
