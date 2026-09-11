import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { TransactionKind, type TransactionPublic } from '@/api'
import { Component as TransactionsPage } from '@/pages/transactions'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    transactionsListTransactions: vi.fn(),
    transactionsDeleteTransaction: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR' } }),
}))

vi.mock('@/hooks/use-accounts', () => ({
  useAccounts: () => ({ data: { data: [{ id: 'a1', name: 'Current' }] } }),
}))

vi.mock('@/hooks/use-categories', () => ({
  useCategories: () => ({ data: { data: [] } }),
  useCategoryTree: () => ({ data: [] }),
}))

const api = await import('@/api')

function aTransaction(overrides: Partial<TransactionPublic> = {}): TransactionPublic {
  return {
    id: 't1',
    household_id: 'h1',
    account_id: 'a1',
    kind: TransactionKind.INCOME,
    amount_minor: 5000,
    occurred_on: '2026-09-08',
    merchant: 'Session',
    is_generated: true,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderPage(transaction: TransactionPublic) {
  vi.mocked(api.transactionsListTransactions).mockResolvedValue({
    data: { data: [transaction], count: 1 },
  } as never)

  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <TransactionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('income a session generated', () => {
  it('is labelled as a session, not as recurring', async () => {
    // It carries is_generated, but nothing here repeats on a schedule. The
    // badge was saying the one thing about the row that is not true.
    renderPage(aTransaction({ income_session_id: 's1' }))

    // Twice over: the ledger label the row was written with, and the badge.
    expect(await screen.findAllByText('Session')).toHaveLength(2)
    expect(screen.queryByText('Recurring')).not.toBeInTheDocument()
  })

  it('offers no edit or delete, because the API refuses both', async () => {
    // The session holds the fee. Offering the actions here would only produce
    // a 409 and an error toast.
    renderPage(aTransaction({ income_session_id: 's1' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Manage transaction' }))

    expect(screen.queryByRole('menuitem', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('points at the one place it can be changed', async () => {
    renderPage(aTransaction({ income_session_id: 's1' }))

    await userEvent.click(await screen.findByRole('button', { name: 'Manage transaction' }))

    expect(
      await screen.findByRole('menuitem', { name: 'Change it on the Income page' }),
    ).toBeInTheDocument()
  })
})

describe('an ordinary recurring transaction', () => {
  it('keeps its badge and both actions', async () => {
    renderPage(aTransaction({ merchant: 'Netflix', kind: TransactionKind.EXPENSE }))

    expect(await screen.findByText('Recurring')).toBeInTheDocument()

    await userEvent.click(await screen.findByRole('button', { name: 'Manage transaction' }))

    expect(await screen.findByRole('menuitem', { name: 'Edit' })).toBeInTheDocument()
    expect(await screen.findByRole('menuitem', { name: 'Delete' })).toBeInTheDocument()
  })
})

describe('the amount cell', () => {
  // The column is the one place a reader sees which way the money went, so
  // the sign on it carries the whole meaning of the row.
  async function rowFor(merchant: string) {
    return (await screen.findByText(merchant)).closest('tr')
  }

  it('draws spending with a minus', async () => {
    renderPage(
      aTransaction({ merchant: 'Groceries', kind: TransactionKind.EXPENSE, amount_minor: 50_000 }),
    )

    expect(await rowFor('Groceries')).toHaveTextContent('-€500.00')
  })

  it('draws income with a plus', async () => {
    renderPage(
      aTransaction({ merchant: 'Salary', kind: TransactionKind.INCOME, amount_minor: 300_000 }),
    )

    expect(await rowFor('Salary')).toHaveTextContent('+€3,000.00')
  })
})
