import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { HouseholdRole } from '@/api'
import { InviteBanner } from '@/components/layout/invite-banner'

// The banner talks to the generated client directly, so the tests stand in for
// the two endpoints: what matters is that an invitation waiting for the account
// is offered, and that accepting it uses the invitation's ID.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    householdsListReceivedHouseholdInvites: vi.fn(),
    householdsAcceptReceivedHouseholdInvite: vi.fn(),
  }
})

const api = await import('@/api')

function invitesAre(data: object[]) {
  vi.mocked(api.householdsListReceivedHouseholdInvites).mockResolvedValue({
    data: { data, count: data.length },
  } as never)
}

const INVITE = {
  id: 'i1',
  household_name: 'mourgkanas 10',
  invited_by: 'admin@example.com',
  role: HouseholdRole.MEMBER,
  expires_at: '2026-10-17T10:00:00Z',
}

/** Stands in for a screen that stays mounted beside the banner, like the shell. */
function Beside({ queryKey, queryFn }: { queryKey: string; queryFn: () => Promise<string> }) {
  const { data } = useQuery({ queryKey: [queryKey], queryFn })
  return <p>{data}</p>
}

function renderBanner(beside: React.ReactNode = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <InviteBanner />
        {beside}
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('InviteBanner', () => {
  it('says nothing when no invitation is waiting', async () => {
    invitesAre([])

    renderBanner()

    await waitFor(() => expect(api.householdsListReceivedHouseholdInvites).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Join household' })).not.toBeInTheDocument()
  })

  it('offers an invitation waiting for the account', async () => {
    invitesAre([INVITE])

    renderBanner()

    expect(await screen.findByText('Join mourgkanas 10')).toBeInTheDocument()
    expect(screen.getByText(/admin@example.com invited you as a member/)).toBeInTheDocument()
  })

  it('accepts the invitation by its ID', async () => {
    invitesAre([INVITE])
    vi.mocked(api.householdsAcceptReceivedHouseholdInvite).mockResolvedValue({
      data: { id: 'h1', name: 'mourgkanas 10' },
    } as never)

    renderBanner()
    await userEvent.click(await screen.findByRole('button', { name: 'Join household' }))

    await waitFor(() =>
      expect(api.householdsAcceptReceivedHouseholdInvite).toHaveBeenCalledWith({
        path: { invite_id: 'i1' },
      }),
    )
  })

  it('reloads what is on screen after joining, without a page refresh', async () => {
    invitesAre([INVITE])
    vi.mocked(api.householdsAcceptReceivedHouseholdInvite).mockResolvedValue({
      data: { id: 'h1', name: 'mourgkanas 10' },
    } as never)
    const household = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce('Lover household')
      .mockResolvedValue('mourgkanas 10')
    const currentUser = vi.fn<() => Promise<string>>().mockResolvedValue('lover@example.com')

    renderBanner(
      <>
        <Beside queryKey="household" queryFn={household} />
        <Beside queryKey="currentUser" queryFn={currentUser} />
      </>,
    )
    expect(await screen.findByText('Lover household')).toBeInTheDocument()
    invitesAre([])
    await userEvent.click(await screen.findByRole('button', { name: 'Join household' }))

    // The household the user joined replaces the one they left, and the
    // banner goes, both without a reload.
    expect(await screen.findByText('mourgkanas 10')).toBeInTheDocument()
    expect(screen.queryByText('Lover household')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Join household' })).not.toBeInTheDocument()
    // The signed-in user is the same person, so it is not fetched again.
    expect(currentUser).toHaveBeenCalledTimes(1)
  })

  it('hides an invitation the user put off', async () => {
    invitesAre([INVITE])

    renderBanner()
    await userEvent.click(await screen.findByRole('button', { name: 'Not now' }))

    expect(screen.queryByText('Join mourgkanas 10')).not.toBeInTheDocument()
  })
})
