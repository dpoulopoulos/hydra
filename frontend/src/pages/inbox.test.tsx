import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BankTransactionPublic } from '@/api'
import { Component as InboxPage } from '@/pages/inbox'

// The page and its dialog talk to the generated client directly, so the tests
// stand in for the endpoints rather than for the components' own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    goalsListGoals: vi.fn(),
    bankListBankInbox: vi.fn(),
    bankAcceptBankTransaction: vi.fn(),
    bankSkipBankTransaction: vi.fn(),
    bankReopenBankTransaction: vi.fn(),
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const api = await import('@/api')

const CURRENT = 'a-current'
const SAVINGS = 'a-savings'

function account(id: string, name: string) {
  return {
    id,
    name,
    type: 'checking',
    household_id: 'h',
    currency_code: 'EUR',
    opening_balance_minor: 0,
    opening_balance_date: '2026-01-01',
    archived_at: null,
  }
}

function row(overrides: Partial<BankTransactionPublic> = {}): BankTransactionPublic {
  return {
    id: 'r1',
    bank_account_id: 'b1',
    bank_account_name: 'Everyday account',
    account_id: CURRENT,
    direction: 'debit',
    amount_minor: 420,
    currency_code: 'EUR',
    occurred_on: '2026-10-05',
    counterparty_name: 'Coffee Island',
    description: 'CARD 1234',
    review_status: 'pending',
    created_at: '2026-10-06T00:00:00Z',
    ...overrides,
  }
}

function inboxHolds(...rows: BankTransactionPublic[]) {
  vi.mocked(api.bankListBankInbox).mockResolvedValue({
    data: { data: rows, count: rows.length },
  } as never)
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <InboxPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: [account(CURRENT, 'Current'), account(SAVINGS, 'Savings')], count: 2 },
  } as never)
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: { data: [{ id: 'cat-food', name: 'Food', children: [] }], count: 1 },
  } as never)
  vi.mocked(api.goalsListGoals).mockResolvedValue({ data: { data: [], count: 0 } } as never)
})

describe('the inbox', () => {
  it('lists what is waiting, as money out of the linked account', async () => {
    inboxHolds(row())

    renderPage()

    const table = within(await screen.findByRole('table'))
    expect(table.getByText('Coffee Island')).toBeInTheDocument()
    expect(table.getByText('CARD 1234')).toBeInTheDocument()
    expect(await table.findByText('Current')).toBeInTheDocument()
    expect(table.getByText('-€4.20')).toBeInTheDocument()
    expect(api.bankListBankInbox).toHaveBeenCalledWith({
      query: { status: 'pending', skip: 0, limit: 50 },
    })
  })

  it('asks for a link before a row from an unlinked bank account can be accepted', async () => {
    inboxHolds(row({ account_id: null }))

    renderPage()

    expect(await screen.findByRole('link', { name: 'Link account' })).toHaveAttribute(
      'href',
      '/settings/bank',
    )
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument()
  })

  it('skips a row without asking', async () => {
    inboxHolds(row())
    vi.mocked(api.bankSkipBankTransaction).mockResolvedValue({ data: row() } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Skip' }))

    await waitFor(() =>
      expect(api.bankSkipBankTransaction).toHaveBeenCalledWith({
        path: { bank_transaction_id: 'r1' },
      }),
    )
  })

  it('puts a skipped row back', async () => {
    inboxHolds(row({ review_status: 'skipped' }))
    vi.mocked(api.bankReopenBankTransaction).mockResolvedValue({ data: row() } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('tab', { name: 'Skipped' }))
    await user.click(await screen.findByRole('button', { name: 'Put back' }))

    await waitFor(() => expect(api.bankReopenBankTransaction).toHaveBeenCalled())
    expect(api.bankListBankInbox).toHaveBeenCalledWith({
      query: { status: 'skipped', skip: 0, limit: 50 },
    })
  })
})

describe('accepting a row', () => {
  it('records spending in the chosen category, with the bank words kept', async () => {
    inboxHolds(row())
    vi.mocked(api.bankAcceptBankTransaction).mockResolvedValue({ data: row() } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Accept' }))
    const dialog = within(await screen.findByRole('dialog'))
    // Money out is spending or a transfer out, never income.
    expect(dialog.queryByRole('tab', { name: 'Income' })).not.toBeInTheDocument()
    expect(dialog.getByLabelText('Merchant')).toHaveValue('Coffee Island')
    await user.click(dialog.getByRole('combobox', { name: 'Category' }))
    await user.click(await screen.findByRole('option', { name: 'Food' }))
    await user.click(dialog.getByRole('button', { name: 'Accept' }))

    await waitFor(() =>
      expect(api.bankAcceptBankTransaction).toHaveBeenCalledWith({
        path: { bank_transaction_id: 'r1' },
        body: {
          kind: 'expense',
          category_id: 'cat-food',
          counter_account_id: null,
          goal_id: null,
          merchant: 'Coffee Island',
          note: 'CARD 1234',
        },
      }),
    )
  })

  it('records money in as a transfer from another account', async () => {
    inboxHolds(row({ direction: 'credit' }))
    vi.mocked(api.bankAcceptBankTransaction).mockResolvedValue({ data: row() } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Accept' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.click(dialog.getByRole('tab', { name: 'Transfer in' }))
    // The other side is needed, so the form says so rather than sending it.
    await user.click(dialog.getByRole('button', { name: 'Accept' }))
    expect(await dialog.findByText('Choose the other account.')).toBeInTheDocument()

    await user.click(dialog.getByRole('combobox', { name: 'From account' }))
    const listbox = within(await screen.findByRole('listbox'))
    // The linked account is the side the bank already fixed.
    expect(listbox.queryByRole('option', { name: 'Current' })).not.toBeInTheDocument()
    await user.click(listbox.getByRole('option', { name: 'Savings' }))
    // Picking one answers the complaint, before anything is sent again.
    await waitFor(() =>
      expect(dialog.queryByText('Choose the other account.')).not.toBeInTheDocument(),
    )
    await user.click(dialog.getByRole('button', { name: 'Accept' }))

    await waitFor(() =>
      expect(api.bankAcceptBankTransaction).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            kind: 'transfer',
            counter_account_id: SAVINGS,
            category_id: null,
          }),
        }),
      ),
    )
  })

  it('keeps the dialog open and says why when the API refuses', async () => {
    inboxHolds(row())
    vi.mocked(api.bankAcceptBankTransaction).mockResolvedValue({
      error: { detail: 'This bank transaction was already accepted.' },
    } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Accept' }))
    const dialog = within(await screen.findByRole('dialog'))
    await user.click(dialog.getByRole('button', { name: 'Accept' }))

    expect(
      await dialog.findByText('This bank transaction was already accepted.'),
    ).toBeInTheDocument()
  })
})
