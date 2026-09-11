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

function householdIsNamed(name: string, locale: string | null = null) {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h1', name, currency_code: 'EUR', locale },
  } as never)
}

/** One outstanding invitation, as the endpoint hands it back. */
function pendingInvite() {
  return {
    id: 'i1',
    email: 'ada@example.com',
    role: HouseholdRole.MEMBER,
    status: 'pending',
    expires_at: '2026-10-01T10:00:00Z',
  }
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

  it('asks for one page rather than every invitation ever sent', async () => {
    renderHousehold()

    await waitFor(() => expect(api.householdsListHouseholdInvites).toHaveBeenCalled())
    const call = vi.mocked(api.householdsListHouseholdInvites).mock.calls[0][0] as {
      query: { limit?: number }
    }
    expect(call.query.limit).toBeGreaterThan(0)
  })

  it('says how many outstanding invitations did not fit on the page', async () => {
    vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
      data: { data: [pendingInvite()], count: 60 },
    } as never)
    renderHousehold()

    expect(await screen.findByText('Showing 1 of 60 outstanding invitations.')).toBeInTheDocument()
  })

  it('says nothing about a page that holds everything outstanding', async () => {
    vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
      data: { data: [pendingInvite()], count: 1 },
    } as never)
    renderHousehold()

    expect(await screen.findByText('ada@example.com')).toBeInTheDocument()
    expect(screen.queryByText(/Showing 1 of/)).not.toBeInTheDocument()
  })

  it('reads emptiness from the invitations it was handed, not from the count', async () => {
    // The count reports the whole match now, so a page that came back empty
    // is the only thing that can say there is nothing to show.
    vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
      data: { data: [], count: 3 },
    } as never)
    renderHousehold()

    expect(await screen.findByText('No invitations outstanding.')).toBeInTheDocument()
  })

  /** Answers the invites query with one outstanding invitation. */
  function oneInviteThatWas(delivery_status: string | null) {
    vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
      data: {
        data: [
          {
            id: 'i1',
            household_id: 'h1',
            email: 'partner@example.com',
            role: HouseholdRole.MEMBER,
            status: 'pending',
            expires_at: '2099-01-01T00:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
            delivery_status,
          },
        ],
        count: 1,
      },
    } as never)
  }

  it('flags an invitation whose email never went out', async () => {
    // Without this the owner waits on an invitation that nobody was told about.
    oneInviteThatWas('failed')
    renderHousehold()

    expect(await screen.findByText('Not delivered')).toBeInTheDocument()
    expect(screen.getByText(/Withdraw it and invite them again/)).toBeInTheDocument()
  })

  it('says an invitation is still on its way while its email is queued', async () => {
    oneInviteThatWas('pending')
    renderHousehold()

    expect(await screen.findByText('Sending')).toBeInTheDocument()
    expect(screen.queryByText('Not delivered')).not.toBeInTheDocument()
  })

  it('claims nothing about an invitation whose email is settled or unknown', async () => {
    // A delivered message, mail switched off and a pruned outbox row all read
    // the same from here: there is nothing to warn about.
    oneInviteThatWas(null)
    renderHousehold()

    expect(await screen.findByText('partner@example.com')).toBeInTheDocument()
    expect(screen.queryByText('Not delivered')).not.toBeInTheDocument()
    expect(screen.queryByText('Sending')).not.toBeInTheDocument()
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

// A household picks one way of writing numbers for everyone in it, or leaves
// every reader to their own browser, which is what it always did.
describe('how the household writes numbers', () => {
  const numbersField = () => screen.getByRole('combobox', { name: 'Numbers' })

  it('starts on the browser for a household that has chosen nothing', async () => {
    renderHousehold()

    await waitFor(() => expect(numbersField()).toHaveTextContent("Each reader's browser"))
  })

  it('shows the locale the household has chosen, with an amount written its way', async () => {
    householdIsNamed('Rivera', 'de-DE')
    renderHousehold()

    await waitFor(() => expect(numbersField()).toHaveTextContent('123.456,78'))
  })

  it('saves the locale the owner picks', async () => {
    const person = userEvent.setup()
    vi.mocked(api.householdsUpdateHouseholdMe).mockResolvedValue({ data: {} } as never)
    renderHousehold()

    await waitFor(() => expect(numbersField()).toBeEnabled())
    await person.click(numbersField())
    // Named rather than matched on the sample: more than one locale writes
    // an amount this way, which is the point of showing the sample at all.
    await person.click(await screen.findByRole('option', { name: /Deutsch \(Deutschland\)/ }))

    await waitFor(() => expect(api.householdsUpdateHouseholdMe).toHaveBeenCalled())
    expect(vi.mocked(api.householdsUpdateHouseholdMe).mock.calls[0][0]).toMatchObject({
      body: { locale: 'de-DE' },
    })
  })

  it('hands the choice back to the browser when that is what is picked', async () => {
    const person = userEvent.setup()
    vi.mocked(api.householdsUpdateHouseholdMe).mockResolvedValue({ data: {} } as never)
    householdIsNamed('Rivera', 'de-DE')
    renderHousehold()

    await waitFor(() => expect(numbersField()).toHaveTextContent('123.456,78'))
    await person.click(numbersField())
    await person.click(await screen.findByRole('option', { name: /Each reader's browser/ }))

    await waitFor(() => expect(api.householdsUpdateHouseholdMe).toHaveBeenCalled())
    expect(vi.mocked(api.householdsUpdateHouseholdMe).mock.calls[0][0]).toMatchObject({
      body: { locale: null },
    })
  })

  it('says when a member was made owner because the household had none', async () => {
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
          {
            id: 'm2',
            user_id: 'u-heir',
            email: 'heir@example.com',
            full_name: 'Bo',
            role: HouseholdRole.OWNER,
            promoted_to_owner_at: '2026-03-01T10:00:00Z',
          },
        ],
        count: 2,
      },
    } as never)
    renderHousehold()

    // Whoever reads this page can see the household changed hands by itself,
    // rather than that Bo was given the role by somebody.
    expect(await screen.findByText(/left without an owner/)).toBeInTheDocument()
  })

  it('says nothing about a promotion for an owner who was made one', async () => {
    renderHousehold()

    await waitFor(() => expect(nameField()).toHaveValue('Rivera'))
    expect(screen.queryByText(/left without an owner/)).not.toBeInTheDocument()
  })

  it('is left to look at by a member who does not own the household', async () => {
    vi.mocked(api.householdsListHouseholdMembers).mockResolvedValue({
      data: {
        data: [
          {
            id: 'm1',
            user_id: OWNER,
            email: 'owner@example.com',
            role: HouseholdRole.MEMBER,
          },
        ],
        count: 1,
      },
    } as never)
    renderHousehold()

    await waitFor(() => expect(numbersField()).toBeDisabled())
  })
})
