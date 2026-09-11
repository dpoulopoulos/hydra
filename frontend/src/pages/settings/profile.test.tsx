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
    emailVerificationCancelPendingEmailChangeMe: vi.fn(),
    emailVerificationGetPendingEmailChangeMe: vi.fn(),
    emailVerificationResendPendingEmailChangeMe: vi.fn(),
    emailVerificationSendVerificationEmailMe: vi.fn(),
    usersUpdateUserMe: vi.fn(),
    usersUpdatePasswordMe: vi.fn(),
    usersDeleteUserMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

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
    vi.mocked(api.emailVerificationCancelPendingEmailChangeMe).mockResolvedValue({
      data: { message: 'Email change cancelled.' },
    } as never)
    vi.mocked(api.emailVerificationSendVerificationEmailMe).mockResolvedValue({
      data: { message: 'Verification email sent successfully.' },
    } as never)
    vi.mocked(api.emailVerificationResendPendingEmailChangeMe).mockResolvedValue({
      data: { message: 'Verification email sent to the new address.' },
    } as never)
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

  it('calls the change off when asked to', async () => {
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Cancel the change' }))

    // Nothing to put back: the account never left the address it holds.
    await waitFor(() => expect(api.emailVerificationCancelPendingEmailChangeMe).toHaveBeenCalled())
    expect(toast.success).toHaveBeenCalledWith('Email change cancelled')
  })

  it('drops the notice once the change is called off', async () => {
    renderProfile()
    const person = userEvent.setup()

    // Once the change is called off, the refetch that follows finds nothing
    // outstanding.
    vi.mocked(api.emailVerificationCancelPendingEmailChangeMe).mockImplementation(() => {
      vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
        data: null,
      } as never)
      return Promise.resolve({ data: { message: 'Email change cancelled.' } }) as never
    })

    await person.click(await screen.findByRole('button', { name: 'Cancel the change' }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('owns up when asking for a confirmation calls the change off', async () => {
    renderProfile()
    const person = userEvent.setup()

    // Issuing a confirmation expires the account's pending row, change of
    // address and all, so the button drops the change without being asked to.
    await person.click(await screen.findByRole('button', { name: 'Send confirmation email' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Confirmation email sent. The change to moving-to@example.com was cancelled.',
      ),
    )
  })

  it('drops the notice once a confirmation is asked for', async () => {
    renderProfile()
    const person = userEvent.setup()

    vi.mocked(api.emailVerificationSendVerificationEmailMe).mockImplementation(() => {
      vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
        data: null,
      } as never)
      return Promise.resolve({
        data: { message: 'Verification email sent successfully.' },
      }) as never
    })

    await person.click(await screen.findByRole('button', { name: 'Send confirmation email' }))

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('treats a change that has already gone as called off', async () => {
    // The link was opened, or the change lapsed, between the notice being
    // drawn and the button being pressed. The account wanted it gone and it is
    // gone, so say so in the screen's words rather than the backend's.
    vi.mocked(api.emailVerificationCancelPendingEmailChangeMe).mockImplementation(() => {
      vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
        data: null,
      } as never)
      return Promise.resolve({
        error: { detail: 'Email verification not found.', status: 404 },
      }) as never
    })
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Cancel the change' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('That change is no longer outstanding.'),
    )
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('says why calling the change off failed', async () => {
    vi.mocked(api.emailVerificationCancelPendingEmailChangeMe).mockResolvedValue({
      error: { detail: 'Email verification not found.' },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Cancel the change' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
  })

  it('sends the link again without being told where to', async () => {
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send the link again' }))

    // No address is passed: the pending change is what says where it goes, so
    // the button cannot re-aim it at a mailbox nobody asked for.
    await waitFor(() =>
      expect(api.emailVerificationResendPendingEmailChangeMe).toHaveBeenCalledWith(),
    )
    expect(toast.success).toHaveBeenCalledWith('Link sent again. Check the new address.')
  })

  it('says how long the new link has, not how long the old one had', async () => {
    const resent = { ...pendingChange, expires_at: '2026-03-11T14:30:00Z' }
    vi.mocked(api.emailVerificationResendPendingEmailChangeMe).mockImplementation(() => {
      vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
        data: resent,
      } as never)
      return Promise.resolve({
        data: { message: 'Verification email sent to the new address.' },
      }) as never
    })
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send the link again' }))

    // A fresh link comes with a fresh deadline, and a notice still quoting the
    // old one is describing a link that no longer exists.
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(formatDateTime(resent.expires_at)),
    )
  })

  it('treats a change that has gone as nothing left to send', async () => {
    vi.mocked(api.emailVerificationResendPendingEmailChangeMe).mockImplementation(() => {
      vi.mocked(api.emailVerificationGetPendingEmailChangeMe).mockResolvedValue({
        data: null,
      } as never)
      return Promise.resolve({
        error: { detail: 'Email verification not found.', status: 404 },
      }) as never
    })
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send the link again' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('That change is no longer outstanding.'),
    )
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('says why sending the link again failed', async () => {
    vi.mocked(api.emailVerificationResendPendingEmailChangeMe).mockResolvedValue({
      error: { detail: 'Boom.' },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send the link again' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalled())
  })

  it('does not send anyone to the new address while the link is still queued', async () => {
    // The provider has not taken the message yet. It is written down and goes out minutes
    // later, so "check the new address" would send somebody to look at nothing.
    vi.mocked(api.emailVerificationResendPendingEmailChangeMe).mockResolvedValue({
      data: { message: 'Verification email queued for delivery.', delivery: 'queued' },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send the link again' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Still sending the link to the new address. It should arrive shortly.',
      ),
    )
  })

  it('owns up when the server sends no link at all', async () => {
    vi.mocked(api.emailVerificationResendPendingEmailChangeMe).mockResolvedValue({
      data: { message: 'Email delivery is not configured.', delivery: 'not_configured' },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send the link again' }))

    // Nothing was sent and nothing is coming, so this is not success to dress up.
    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        'Email is not set up on this server, so no link was sent.',
      ),
    )
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('does not send anyone to their inbox while the confirmation is still queued', async () => {
    vi.mocked(api.emailVerificationSendVerificationEmailMe).mockResolvedValue({
      data: { message: 'Verification email queued for delivery.', delivery: 'queued' },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send confirmation email' }))

    // Whatever the provider did, the pending change is expired by the request, so the screen
    // still has to say what asking for the confirmation cost.
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Still sending the confirmation email. It should arrive shortly.' +
          ' The change to moving-to@example.com was cancelled.',
      ),
    )
  })

  it('owns up when no confirmation could be sent, change called off and all', async () => {
    vi.mocked(api.emailVerificationSendVerificationEmailMe).mockResolvedValue({
      data: { message: 'Email delivery is not configured.', delivery: 'not_configured' },
    } as never)
    renderProfile()
    const person = userEvent.setup()

    await person.click(await screen.findByRole('button', { name: 'Send confirmation email' }))

    await waitFor(() =>
      expect(toast.warning).toHaveBeenCalledWith(
        'Email is not set up on this server, so no confirmation was sent.' +
          ' The change to moving-to@example.com was cancelled.',
      ),
    )
    expect(toast.success).not.toHaveBeenCalled()
  })
})
