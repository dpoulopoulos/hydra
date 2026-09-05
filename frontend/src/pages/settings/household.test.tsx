import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HouseholdRole } from '@/api'
import { AuthContext } from '@/lib/auth-context'
import { Component as Household } from '@/pages/settings/household'
import { session } from '@/test/auth'

// The screen talks to the generated client directly, so the tests stand in for
// the endpoints: what matters here is what an owner is told about their
// outstanding invitations when that list fails to arrive, and that a refetch
// landing mid-rename is a state the tests can produce.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    householdsGetHouseholdMe: vi.fn(),
    householdsListHouseholdMembers: vi.fn(),
    householdsListHouseholdInvites: vi.fn(),
    householdsUpdateHouseholdMe: vi.fn(),
    householdsCreateHouseholdInvite: vi.fn(),
  }
})

const api = await import('@/api')

const OWNER = 'u-owner'

const auth = session({
  user: { id: OWNER, email: 'owner@example.com', full_name: 'Ada', is_active: true } as never,
  isAuthenticated: true,
})

function householdIsNamed(name: string) {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h1', name, currency_code: 'EUR' },
  } as never)
}

function renderHousehold() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter>
          <Household />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
  return {
    /** Answers the household query again, the way a window focus would. */
    refetch: async (name: string) => {
      householdIsNamed(name)
      await act(async () => {
        await client.refetchQueries({ queryKey: ['household'] })
      })
    },
  }
}

const nameField = () => screen.getByLabelText('Name')

beforeEach(() => {
  vi.clearAllMocks()
  householdIsNamed('Rivera')
  // Only an owner sees the invitations card, or the rename button, at all.
  vi.mocked(api.householdsListHouseholdMembers).mockResolvedValue({
    data: {
      data: [
        {
          id: 'm1',
          user_id: OWNER,
          email: 'owner@example.com',
          full_name: 'Ada',
          role: HouseholdRole.OWNER,
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
})

describe('household settings page', () => {
  it('shows the household name once it has loaded', async () => {
    renderHousehold()
    await waitFor(() => expect(nameField()).toHaveValue('Rivera'))
  })

  it('keeps a rename in progress when the household is fetched again', async () => {
    const person = userEvent.setup()
    vi.mocked(api.householdsUpdateHouseholdMe).mockResolvedValue({ data: {} } as never)
    const { refetch } = renderHousehold()
    await waitFor(() => expect(nameField()).toHaveValue('Rivera'))

    await person.clear(nameField())
    await person.type(nameField(), 'Rivera House')

    await refetch('Rivera Household')

    expect(nameField()).toHaveValue('Rivera House')

    // What is on screen is what is saved: a refetch mid-edit must not leave
    // the form submitting a name the field never showed.
    await person.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(api.householdsUpdateHouseholdMe).toHaveBeenCalled())
    expect(vi.mocked(api.householdsUpdateHouseholdMe).mock.calls[0][0]).toMatchObject({
      body: { name: 'Rivera House' },
    })
  })

  it('takes on a name changed elsewhere while nothing is being edited', async () => {
    const { refetch } = renderHousehold()
    await waitFor(() => expect(nameField()).toHaveValue('Rivera'))

    await refetch('Rivera Household')

    await waitFor(() => expect(nameField()).toHaveValue('Rivera Household'))
  })

  it('still follows the server after a rename of its own', async () => {
    const person = userEvent.setup()
    vi.mocked(api.householdsUpdateHouseholdMe).mockResolvedValue({ data: {} } as never)
    const { refetch } = renderHousehold()
    await waitFor(() => expect(nameField()).toHaveValue('Rivera'))

    await person.clear(nameField())
    await person.type(nameField(), 'Rivera House')
    await person.click(screen.getByRole('button', { name: 'Save name' }))
    await waitFor(() => expect(api.householdsUpdateHouseholdMe).toHaveBeenCalled())
    await refetch('Rivera House')

    // Saving is not editing: the field is level with the server again, so a
    // name changed elsewhere afterwards still reaches it.
    await refetch('Rivera Household')
    await waitFor(() => expect(nameField()).toHaveValue('Rivera Household'))
  })
})

describe('the invitations list', () => {
  it('says it did not load rather than that there are none outstanding', async () => {
    vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
      error: { detail: 'Invitations are unavailable.' },
    } as never)
    renderHousehold()

    expect(await screen.findByText('Invitations are unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('No invitations outstanding.')).not.toBeInTheDocument()
  })

  it('still says so when there genuinely are none outstanding', async () => {
    renderHousehold()

    expect(await screen.findByText('No invitations outstanding.')).toBeInTheDocument()
  })
})

describe('inviting someone', () => {
  /** The body the last invite call sent. */
  function invitedBody() {
    const call = vi.mocked(api.householdsCreateHouseholdInvite).mock.calls.at(-1)
    return (call?.[0] as { body: Record<string, unknown> }).body
  }

  beforeEach(() => {
    vi.mocked(api.householdsCreateHouseholdInvite).mockResolvedValue({ data: {} } as never)
  })

  it('invites them as a member unless another role is picked', async () => {
    const person = userEvent.setup()
    renderHousehold()

    await person.type(await screen.findByLabelText('Email'), 'partner@example.com')
    expect(screen.getByRole('combobox', { name: 'Role' })).toHaveTextContent('Member')

    await person.click(screen.getByRole('button', { name: 'Send invitation' }))

    await waitFor(() => expect(api.householdsCreateHouseholdInvite).toHaveBeenCalled())
    expect(invitedBody()).toEqual({ email: 'partner@example.com', role: 'member' })
  })

  it('invites them as an owner when that is the role picked', async () => {
    const person = userEvent.setup()
    renderHousehold()

    await person.type(await screen.findByLabelText('Email'), 'partner@example.com')
    await person.click(screen.getByRole('combobox', { name: 'Role' }))
    await person.click(await screen.findByRole('option', { name: 'Owner' }))

    expect(screen.getByRole('combobox', { name: 'Role' })).toHaveTextContent('Owner')

    await person.click(screen.getByRole('button', { name: 'Send invitation' }))

    await waitFor(() => expect(api.householdsCreateHouseholdInvite).toHaveBeenCalled())
    expect(invitedBody()).toEqual({ email: 'partner@example.com', role: 'owner' })
  })
})
