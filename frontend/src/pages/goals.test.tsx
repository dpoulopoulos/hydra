import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GoalAccountSummary, GoalPublic } from '@/api'
import { formatMoney } from '@/lib/money'
import { Component as GoalsPage } from '@/pages/goals'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    goalsListGoals: vi.fn(),
    goalsUpdateGoal: vi.fn(),
    goalsDeleteGoal: vi.fn(),
    goalsGetGoalHistory: vi.fn(),
    accountsListAccounts: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR' } }),
  useIsHouseholdOwner: () => true,
}))

const api = await import('@/api')

const SAVINGS = 'savings'

function aGoal(overrides: Partial<GoalPublic> = {}): GoalPublic {
  return {
    id: 'g1',
    household_id: 'h1',
    account_id: SAVINGS,
    account_name: 'Rainy day',
    currency_code: 'EUR',
    name: 'New car',
    target_minor: 2_000_000,
    saved_minor: 500_000,
    peak_saved_minor: 500_000,
    remaining_minor: 1_500_000,
    progress: 0.25,
    average_monthly_minor: 0,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function anAccount(overrides: Partial<GoalAccountSummary> = {}): GoalAccountSummary {
  return {
    account_id: SAVINGS,
    account_name: 'Rainy day',
    currency_code: 'EUR',
    balance_minor: 600_000,
    assigned_minor: 500_000,
    unassigned_minor: 100_000,
    ...overrides,
  }
}

function renderPage(goals: GoalPublic[], accounts: GoalAccountSummary[] = [anAccount()]) {
  vi.mocked(api.goalsListGoals).mockResolvedValue({
    data: { data: goals, count: goals.length, accounts },
  } as never)

  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <GoalsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({ data: { data: [], count: 0 } } as never)
  vi.mocked(api.goalsUpdateGoal).mockResolvedValue({ data: {} } as never)
})

describe('the goals page', () => {
  it('invites a first goal when there is none', async () => {
    renderPage([], [])

    expect(await screen.findByText('No goals yet')).toBeInTheDocument()
  })

  it('splits the account into goals and unassigned money', async () => {
    renderPage([aGoal()])

    const card = (await screen.findByText('Rainy day')).closest('[data-slot="card"]') as HTMLElement
    expect(within(card).getByText(formatMoney(600_000, 'EUR'))).toBeInTheDocument()
    expect(card).toHaveTextContent(`${formatMoney(500_000, 'EUR')} in goals`)
    expect(card).toHaveTextContent(`${formatMoney(100_000, 'EUR')} unassigned`)
  })

  it('shows how far a goal has come', async () => {
    renderPage([aGoal()])

    expect(await screen.findByRole('progressbar', { name: 'New car progress' })).toHaveAttribute(
      'aria-valuenow',
      '25',
    )
  })

  it('says what to save each month for a dated goal', async () => {
    renderPage([
      aGoal({
        target_date: '2027-12-31',
        months_left: 15,
        needed_per_month_minor: 100_000,
        on_track: false,
      }),
    ])

    expect(await screen.findByText('Behind')).toBeInTheDocument()
    expect(screen.getByText(/a month to reach it by/)).toHaveTextContent(
      `Save ${formatMoney(100_000, 'EUR')} a month`,
    )
  })

  it('shows a spent goal at the most it held once reached', async () => {
    renderPage([
      aGoal({
        name: 'Laptop',
        target_minor: 120_000,
        saved_minor: 0,
        peak_saved_minor: 120_000,
        remaining_minor: 120_000,
        progress: 0,
        achieved_at: '2026-10-01T00:00:00Z',
      }),
    ])

    const bar = await screen.findByRole('progressbar', { name: 'Laptop progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '100')
    expect(bar.parentElement).toHaveTextContent(
      `${formatMoney(120_000, 'EUR')} of ${formatMoney(120_000, 'EUR')}`,
    )
  })

  it('marks a goal as reached', async () => {
    const user = userEvent.setup()
    renderPage([aGoal()])

    await user.click(await screen.findByRole('button', { name: 'Manage New car' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Mark as reached' }))

    await waitFor(() =>
      expect(api.goalsUpdateGoal).toHaveBeenCalledWith({
        path: { goal_id: 'g1' },
        body: { is_achieved: true },
      }),
    )
  })
})
