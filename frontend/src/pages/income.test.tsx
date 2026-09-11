import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ForecastBasis,
  IncomeSessionStatus,
  PaymentStatus,
  type IncomeClientPublic,
  type IncomeForecast,
  type IncomeSessionPublic,
  type IncomeSummary,
} from '@/api'
import { VaultContext, type VaultValue } from '@/lib/vault-context'
import { Component as IncomePage } from '@/pages/income'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    incomeGetSummary: vi.fn(),
    incomeGetForecast: vi.fn(),
    incomeListSessions: vi.fn(),
    incomeListClients: vi.fn(),
    incomeUpdateSession: vi.fn(),
    incomeUpdateClient: vi.fn(),
    incomeDeleteSession: vi.fn(),
    incomeDeleteClient: vi.fn(),
    householdsUpdateHouseholdMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: USER_ID } }),
}))

// Mutable, so the owner-only branch can actually be entered. Hardcoding it
// would leave the gate on the ledger label untested and free to be removed.
let isOwner = true

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR', session_merchant_label: 'Session' } }),
  useIsHouseholdOwner: () => isOwner,
}))

beforeEach(() => {
  isOwner = true
})

const api = await import('@/api')

const CLIENT_ID = 'c1'
const USER_ID = 'u1'
const OTHER_USER_ID = 'u2'

function aClient(overrides: Partial<IncomeClientPublic> = {}): IncomeClientPublic {
  return {
    id: CLIENT_ID,
    household_id: 'h1',
    owner_user_id: USER_ID,
    // What the server actually stores. The page decrypts it, or shows dots.
    name_ct: 'cipher-for-anna',
    default_rate_minor: 5000,
    cadence_interval: 1,
    cadence_weekdays: [],
    default_account_id: 'a1',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function aSession(overrides: Partial<IncomeSessionPublic> = {}): IncomeSessionPublic {
  return {
    id: 's1',
    household_id: 'h1',
    client_id: CLIENT_ID,
    occurs_on: '2026-09-08',
    fee_minor: 5000,
    status: IncomeSessionStatus.ATTENDED,
    payment_status: PaymentStatus.PENDING,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function aSummary(overrides: Partial<IncomeSummary> = {}): IncomeSummary {
  return {
    month: '2026-09',
    currency_code: 'EUR',
    earned_minor: 100_000,
    received_minor: 80_000,
    outstanding_minor: 20_000,
    total_outstanding_minor: 35_000,
    oldest_unpaid_on: '2026-03-14',
    attended_count: 20,
    unpaid_count: 3,
    scheduled_minor: 0,
    scheduled_count: 0,
    missed_count: 1,
    cancelled_count: 0,
    active_client_count: 6,
    year: 2026,
    year_earned_minor: 1_842_500,
    year_session_count: 371,
    ...overrides,
  }
}

function aForecast(overrides: Partial<IncomeForecast> = {}): IncomeForecast {
  return {
    month: '2026-10',
    currency_code: 'EUR',
    likely_minor: 196_600,
    low_minor: 166_300,
    high_minor: 226_900,
    basis: ForecastBasis.HISTORY,
    months_used: 6,
    history: [],
    booked_minor: 40_000,
    booked_session_count: 8,
    earned_so_far_minor: 0,
    expected_from_diary_minor: 36_000,
    diary_realisation_rate: 0.9,
    trial_count: 24,
    expected_session_count: 22.4,
    new_client_session_rate: 1.5,
    confidence_percent: 95,
    monthly_churn_rate: 0.05,
    expected_client_months: 20,
    client_lifetime_value_minor: 400_000,
    clients: [],
    ...overrides,
  }
}

/** A vault in a given state, without running Argon2id in a unit test. */
function vault(status: VaultValue['status'], names: Record<string, string> = {}): VaultValue {
  return {
    status,
    unlock: vi.fn(),
    setUp: vi.fn(),
    changePin: vi.fn(),
    lock: vi.fn(),
    encrypt: vi.fn(),
    decrypt: (ciphertext: string) => Promise.resolve(names[ciphertext] ?? null),
  }
}

function renderPage(
  options: {
    status?: VaultValue['status']
    names?: Record<string, string>
    sessions?: IncomeSessionPublic[]
    unpaid?: IncomeSessionPublic[]
    clients?: IncomeClientPublic[]
    summary?: Partial<IncomeSummary>
    forecast?: Partial<IncomeForecast>
    /** A count larger than the rows, standing in for a truncated walk. */
    clientCount?: number
  } = {},
) {
  const sessions = options.sessions ?? [aSession()]
  const unpaid = options.unpaid ?? sessions
  const clients = options.clients ?? [aClient()]

  vi.mocked(api.incomeGetSummary).mockResolvedValue({ data: aSummary(options.summary) } as never)
  vi.mocked(api.incomeGetForecast).mockImplementation((request) => {
    const month = (request as { query?: { month?: string } })?.query?.month ?? '2026-10'
    return Promise.resolve({ data: aForecast({ month, ...options.forecast }) }) as never
  })
  vi.mocked(api.incomeListClients).mockResolvedValue({
    data: { data: clients, count: options.clientCount ?? clients.length },
  } as never)
  vi.mocked(api.incomeListSessions).mockImplementation((request) => {
    const isUnpaidQuery = (request as { query?: { payment_status?: string } })?.query
      ?.payment_status
    const rows = isUnpaidQuery ? unpaid : sessions
    return Promise.resolve({
      data: { data: rows, count: rows.length, earned_total_minor: 0, outstanding_total_minor: 0 },
    }) as never
  })

  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <VaultContext
        value={vault(
          options.status ?? 'unlocked',
          options.names ?? { 'cipher-for-anna': 'Anna K.' },
        )}
      >
        <MemoryRouter>
          <IncomePage />
        </MemoryRouter>
      </VaultContext>
    </QueryClientProvider>,
  )
}

describe('the income page', () => {
  it('shows the client name once the vault is unlocked', async () => {
    renderPage()

    expect(await screen.findAllByText('Anna K.')).not.toHaveLength(0)
  })

  it('hides every name while the vault is locked', async () => {
    renderPage({ status: 'locked' })

    expect(await screen.findAllByLabelText('Hidden until you unlock names')).not.toHaveLength(0)
    await waitFor(() => expect(screen.queryByText('Anna K.')).not.toBeInTheDocument())
  })

  it('reports what is owed across every month, not just this one', async () => {
    // A debt from March is still a debt in September, so the tile is not
    // scoped to the month picker below it.
    renderPage()

    expect(await screen.findByText('Owed to you')).toBeInTheDocument()
    expect(await screen.findByText(/Oldest from/)).toBeInTheDocument()
    expect(await screen.findAllByText((text) => text.includes('350'))).not.toHaveLength(0)
  })

  it('offers the ledger label to an owner', async () => {
    renderPage()

    expect(await screen.findByRole('button', { name: 'Ledger label' })).toBeInTheDocument()
  })

  it('hides the ledger label from a member who is not an owner', async () => {
    // The household refuses the change, so the control would only ever be
    // filled in and then refused.
    isOwner = false
    renderPage()

    await screen.findByText('Owed to you')

    expect(screen.queryByRole('button', { name: 'Ledger label' })).not.toBeInTheDocument()
  })

  it('says so when it could not read every name', async () => {
    // The walk is bounded, and a bound reached silently leaves session rows
    // with no name and nothing to explain them.
    renderPage({ clientCount: 9999 })

    expect(await screen.findByText('Some names could not be loaded')).toBeInTheDocument()
  })

  it('says nothing when the whole list came back', async () => {
    renderPage()

    await screen.findByText('Owed to you')

    expect(screen.queryByText('Some names could not be loaded')).not.toBeInTheDocument()
  })

  it('lets the reader choose how many rows to see', async () => {
    renderPage()

    const rows = await screen.findByLabelText('Rows')

    expect(rows).toHaveTextContent('20')
  })

  it('reports the whole year beside the month', async () => {
    // A quiet fortnight moves the month tile a long way and the year tile
    // barely at all, which is the point of having both.
    renderPage()

    expect(await screen.findByText('Earned in 2026')).toBeInTheDocument()
    expect(await screen.findByText('371 sessions so far')).toBeInTheDocument()
  })

  it('shows the forecast as a range, not a single figure', async () => {
    renderPage()

    expect(await screen.findByText(/1,663/)).toBeInTheDocument()
    expect(await screen.findByText(/2,269/)).toBeInTheDocument()
  })

  it('warns when there is not enough history to forecast from', async () => {
    renderPage({ forecast: { basis: ForecastBasis.SINGLE_MONTH, months_used: 1 } })

    expect(await screen.findByText('The estimate is still settling')).toBeInTheDocument()
  })

  it('says when the estimate could only price part of the practice', async () => {
    // The server reads a capped page of the roster, and what is already booked
    // is counted whole, so past the cap the two disagree and the estimate
    // reads low. A bare figure could not say that.
    renderPage({ forecast: { active_client_count: 260, priced_client_count: 200 } })

    expect(await screen.findByText('The estimate covers part of your clients')).toBeInTheDocument()
    expect(await screen.findByText(/200 of your 260 clients/)).toBeInTheDocument()
  })

  it('says nothing when every client was priced', async () => {
    renderPage({ forecast: { active_client_count: 6, priced_client_count: 6 } })

    await screen.findByText('Owed to you')

    expect(screen.queryByText('The estimate covers part of your clients')).not.toBeInTheDocument()
  })

  it('shows what happened and whether it was paid as two separate facts', async () => {
    // An attended session nobody has paid for is both at once, so one badge
    // could only ever tell half the truth.
    renderPage()

    expect(await screen.findAllByText('Attended')).not.toHaveLength(0)
    expect(await screen.findAllByText('Unpaid')).not.toHaveLength(0)
  })

  it('keeps the diary out of the debtors list', async () => {
    // A session next Tuesday is unpaid only in the sense that it has not
    // happened. The server does the narrowing, so the page must ask for it.
    renderPage()

    await screen.findAllByText('Attended')

    const asked = vi
      .mocked(api.incomeListSessions)
      .mock.calls.map((call) => (call[0] as { query?: Record<string, unknown> })?.query)
      .find((query) => query?.payment_status)

    expect(asked?.owed_only).toBe(true)
  })

  it('says so when nobody owes anything', async () => {
    renderPage({ unpaid: [], summary: { total_outstanding_minor: 0, oldest_unpaid_on: null } })

    expect(await screen.findByText('Everybody has paid')).toBeInTheDocument()
  })

  it('offers to set a PIN before there are any clients', async () => {
    renderPage({ status: 'absent', clients: [], sessions: [], unpaid: [] })

    await userEvent.click(await screen.findByRole('tab', { name: 'Clients' }))

    expect(await screen.findByText('No clients yet')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Set a PIN to start' })).toBeInTheDocument()
  })
})

describe('a client another member of the household added', () => {
  it('never shows their name, whatever your PIN is', async () => {
    // Their names are under their key. There is nothing yours can open.
    renderPage({
      status: 'unlocked',
      clients: [aClient({ owner_user_id: OTHER_USER_ID })],
      names: { 'cipher-for-anna': 'Anna K.' },
    })

    expect(await screen.findAllByLabelText("Another member's client")).not.toHaveLength(0)
    expect(screen.queryByText('Anna K.')).not.toBeInTheDocument()
  })

  it('is marked as not yours in the client list', async () => {
    renderPage({ clients: [aClient({ owner_user_id: OTHER_USER_ID })] })

    await userEvent.click(await screen.findByRole('tab', { name: 'Clients' }))

    expect(await screen.findByText('Not yours')).toBeInTheDocument()
  })

  it('is not marked when it is your own', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('tab', { name: 'Clients' }))

    expect(screen.queryByText('Not yours')).not.toBeInTheDocument()
  })

  it('offers no action the API would refuse', async () => {
    // Archiving and deleting need the owner too, not only editing. Offering
    // them would produce a 403 and an error toast, and nothing else.
    renderPage({ clients: [aClient({ owner_user_id: OTHER_USER_ID })] })

    await userEvent.click(await screen.findByRole('tab', { name: 'Clients' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Client actions' }))

    for (const name of ['Edit', 'Archive', 'Delete']) {
      expect(await screen.findByRole('menuitem', { name })).toHaveAttribute('aria-disabled', 'true')
    }
  })

  it('leaves the actions on your own client alone', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('tab', { name: 'Clients' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Client actions' }))

    expect(await screen.findByRole('menuitem', { name: 'Archive' })).not.toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })
})

describe('how the estimate explains itself', () => {
  async function openWorkings() {
    await userEvent.click(await screen.findByRole('button', { name: 'How this is worked out' }))
  }

  it('keeps the workings folded away until asked', async () => {
    // They are not what anybody came to the page for, and left open they push
    // the tables below the fold on every visit.
    renderPage()

    await screen.findByRole('button', { name: 'How this is worked out' })

    expect(screen.queryByText(/24 appointments/)).not.toBeInTheDocument()
  })

  it('says how many appointments the month holds', async () => {
    // The figure has to be checkable against a real diary.
    renderPage()
    await openWorkings()

    expect(await screen.findByText(/24 appointments/)).toBeInTheDocument()
  })

  it('names the share of appointments that usually go ahead', async () => {
    renderPage()
    await openWorkings()

    expect(await screen.findByText(/90 in every 100 go ahead/)).toBeInTheDocument()
  })

  it('counts the clients who have not rung up yet', async () => {
    // No schedule can predict them, so the estimate says out loud that it has
    // allowed for them.
    renderPage()
    await openWorkings()

    expect(
      await screen.findByText(/1.5 more sessions usually arrive from someone new/),
    ).toBeInTheDocument()
  })

  it('says how often the month should land inside the range', async () => {
    renderPage()
    await openWorkings()

    expect(await screen.findByText(/95 months in 100/)).toBeInTheDocument()
  })

  it('says how often clients stop coming and what one is worth', async () => {
    // A client who stops is not a client who cancelled: they take every future
    // appointment with them, which is why a month further off is worth less
    // than the same diary nearer to hand.
    renderPage()
    await openWorkings()

    expect(await screen.findByText(/5 in every 100 clients stop coming/)).toBeInTheDocument()
    expect(await screen.findByText(/one stays 20 months/)).toBeInTheDocument()
  })

  it('says nothing about lifetimes before anyone has finished', async () => {
    renderPage({ forecast: { expected_client_months: null, client_lifetime_value_minor: null } })
    await openWorkings()

    await screen.findByText(/24 appointments/)

    expect(screen.queryByText(/stop coming/)).not.toBeInTheDocument()
  })

  it('falls back to averaging months when there is nothing booked', async () => {
    renderPage({ forecast: { trial_count: 0, new_client_session_rate: 0 } })

    expect(await screen.findByText(/average of the months before it/)).toBeInTheDocument()
  })
})

describe('the estimate for the month in progress', () => {
  it('covers this month by default', async () => {
    // At any point in the month, the question people ask is where they will
    // land by the end of it, not what happens after.
    renderPage()

    expect(await screen.findByRole('group', { name: 'Which month' })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'This', pressed: true })).toBeInTheDocument()
  })

  it('switches to next month when asked', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Next' }))

    expect(await screen.findByRole('button', { name: 'Next', pressed: true })).toBeInTheDocument()
  })

  it('does not call a diary certain', async () => {
    // A booked session can be missed or called off. Only worked hours are
    // facts, and the diary earns no tile of its own.
    renderPage()

    await screen.findByText(/Expected in/)

    expect(screen.queryByText('Certain already')).not.toBeInTheDocument()
    expect(screen.queryByText(/in the diary/)).not.toBeInTheDocument()
  })
})
