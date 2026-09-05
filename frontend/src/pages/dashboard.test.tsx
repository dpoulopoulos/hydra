import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthContext, type AuthValue } from '@/lib/auth-context'
import { Component as Dashboard } from '@/pages/dashboard'

// The page reads its four reports from the generated client, so the tests
// stand in for the endpoints rather than for the queries: what matters here is
// what the screen says when one of those requests comes back a failure.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    reportsMonthSummary: vi.fn(),
    reportsBudgetProgress: vi.fn(),
    reportsIncomeExpense: vi.fn(),
    transactionsListTransactions: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

const api = await import('@/api')

const auth: AuthValue = {
  user: { id: 'u', email: 'someone@example.com', full_name: 'Ada', is_active: true } as never,
  isLoading: false,
  isAuthenticated: true,
  signIn: async () => {},
  signOut: () => {},
}

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={auth}>
        <MemoryRouter>
          <Dashboard />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.reportsMonthSummary).mockResolvedValue({
    data: {
      income_minor: 200000,
      expense_minor: 150000,
      net_minor: 50000,
      net_worth_minor: 900000,
      transaction_count: 12,
      top_categories: [],
    },
  } as never)
  vi.mocked(api.reportsBudgetProgress).mockResolvedValue({ data: { rows: [] } } as never)
  vi.mocked(api.reportsIncomeExpense).mockResolvedValue({
    data: { months: [], total_net_minor: 120000 },
  } as never)
  vi.mocked(api.transactionsListTransactions).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
})

describe('the budgets panel', () => {
  it('says the limits did not load rather than that there are none', async () => {
    vi.mocked(api.reportsBudgetProgress).mockResolvedValue({
      error: { detail: 'Budget progress is unavailable.' },
    } as never)
    renderDashboard()

    expect(await screen.findByText('Budget progress is unavailable.')).toBeInTheDocument()
    expect(screen.queryByText(/No limits set for/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Set budgets' })).not.toBeInTheDocument()
  })

  it('still invites the user to set limits when there genuinely are none', async () => {
    renderDashboard()

    expect(await screen.findByText(/No limits set for/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Set budgets' })).toBeInTheDocument()
  })
})

describe('the latest activity panel', () => {
  it('says the transactions did not load rather than that there are none', async () => {
    vi.mocked(api.transactionsListTransactions).mockResolvedValue({
      error: { detail: 'Transactions are unavailable.' },
    } as never)
    renderDashboard()

    expect(await screen.findByText('Transactions are unavailable.')).toBeInTheDocument()
    expect(screen.queryByText('Nothing recorded yet.')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Record your first transaction' }),
    ).not.toBeInTheDocument()
  })

  it('still invites the first transaction when there genuinely are none', async () => {
    renderDashboard()

    expect(await screen.findByText('Nothing recorded yet.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Record your first transaction' })).toBeInTheDocument()
  })
})

describe('the Saved tile', () => {
  it('gives a reason when the year figures did not load', async () => {
    vi.mocked(api.reportsIncomeExpense).mockResolvedValue({
      error: { detail: 'The yearly report is unavailable.' },
    } as never)
    renderDashboard()

    expect(await screen.findByText(/did not load/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Year' })).toBeDisabled()
  })

  it('offers the year once its figures are in', async () => {
    renderDashboard()

    await vi.waitFor(() => expect(screen.getByRole('button', { name: 'Year' })).toBeEnabled())
    expect(screen.getByText('12 transactions this month')).toBeInTheDocument()
  })
})
