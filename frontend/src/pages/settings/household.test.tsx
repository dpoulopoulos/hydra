import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext } from '@/lib/auth-context'
import { Component as HouseholdSettings } from '@/pages/settings/household'
import { session } from '@/test/auth'

// The screen talks to the generated client directly, so the tests stand in for
// the endpoints: what matters here is what an owner is told about their
// outstanding invitations when that list fails to arrive.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    householdsGetHouseholdMe: vi.fn(),
    householdsListHouseholdMembers: vi.fn(),
    householdsListHouseholdInvites: vi.fn(),
  }
})

const api = await import('@/api')

const OWNER = 'u-owner'

const auth = session({
  user: { id: OWNER, email: 'owner@example.com', full_name: 'Ada', is_active: true } as never,
  isAuthenticated: true,
})

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter>
          <HouseholdSettings />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  // Only an owner sees the invitations card at all.
  vi.mocked(api.householdsListHouseholdMembers).mockResolvedValue({
    data: {
      data: [{ id: 'm', user_id: OWNER, email: 'owner@example.com', role: 'owner' }],
      count: 1,
    },
  } as never)
  vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
})

describe('the invitations list', () => {
  it('says it did not load rather than that there are none outstanding', async () => {
    vi.mocked(api.householdsListHouseholdInvites).mockResolvedValue({
      error: { detail: 'Invitations are unavailable.' },
    } as never)
    renderSettings()

    expect(await screen.findByText('Invitations are unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('No invitations outstanding.')).not.toBeInTheDocument()
  })

  it('still says so when there genuinely are none outstanding', async () => {
    renderSettings()

    expect(await screen.findByText('No invitations outstanding.')).toBeInTheDocument()
  })
})
