import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AccountType, type AccountPublic } from '@/api'
import { Component as AccountsPage } from '@/pages/accounts'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    accountsUpdateAccount: vi.fn(),
    accountsDeleteAccount: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR' } }),
}))

const api = await import('@/api')

// Vitest runs without globals, so nothing clears the call history between
// tests. Without this, a test asserting that no delete was asked for would be
// reading the calls an earlier test made.
beforeEach(() => {
  vi.clearAllMocks()
})

function anAccount(overrides: Partial<AccountPublic> = {}): AccountPublic {
  return {
    id: 'a1',
    household_id: 'h1',
    name: 'Rainy day',
    type: AccountType.SAVINGS,
    currency_code: 'EUR',
    opening_balance_minor: 0,
    opening_balance_date: '2026-01-01',
    current_balance_minor: 0,
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function renderPage(accounts: AccountPublic[] = [anAccount()]) {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: accounts, count: accounts.length, total_balance_minor: 0 },
  } as never)

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AccountsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/**
 * Ask to delete an account and stop at the confirmation.
 *
 * The row menu is the only way in, so the test walks the same path a user
 * does rather than rendering the dialog on its own.
 */
async function openDeleteDialog(name = 'Rainy day') {
  const user = userEvent.setup()
  renderPage([anAccount({ name })])

  const row = (await screen.findByText(name)).closest('tr')
  if (!row) throw new Error(`no row for ${name}`)
  // By its label rather than as the row's only button, so the test keeps
  // pointing at the menu once a row carries a second control.
  await user.click(within(row).getByRole('button', { name: `Manage ${name}` }))
  await user.click(await screen.findByRole('menuitem', { name: /delete/i }))

  return { user, dialog: await screen.findByRole('alertdialog') }
}

describe('the delete confirmation', () => {
  it('names the account it is about to delete', async () => {
    // Arrange & Act: Ask to delete an account
    const { dialog } = await openDeleteDialog()

    // Assert: The title has to say which account, because the menu it came
    // from is closed by the time the dialog is read
    expect(within(dialog).getByText('Delete Rainy day?')).toBeInTheDocument()
  })

  it('names a recurring rule as a blocker too, not transactions alone', async () => {
    // Arrange & Act: Read the dialog before confirming anything
    const { dialog } = await openDeleteDialog()

    // Assert: Recurring rules refuse the delete as surely as transactions do,
    // so an empty ledger is not enough. The copy names them as examples rather
    // than as the whole list, because more references block the delete than
    // the service checks. Read through the accessible description, which is
    // the text the dialog actually hands the user.
    expect(dialog).toHaveAccessibleDescription(/transactions/i)
    expect(dialog).toHaveAccessibleDescription(/recurring rules/i)
  })

  it('leaves the account alone until the delete is confirmed', async () => {
    // Arrange & Act: Open the dialog and back out of it
    const { user, dialog } = await openDeleteDialog()
    await user.click(within(dialog).getByRole('button', { name: /keep it/i }))

    // Assert: Opening the dialog must not be what deletes the account
    expect(api.accountsDeleteAccount).not.toHaveBeenCalled()
  })

  it('deletes the account once confirmed', async () => {
    // Arrange: A delete the server accepts
    vi.mocked(api.accountsDeleteAccount).mockResolvedValue({ data: undefined } as never)
    const { user, dialog } = await openDeleteDialog()

    // Act: Confirm
    await user.click(within(dialog).getByRole('button', { name: /delete account/i }))

    // Assert: The account the dialog named is the one asked for
    expect(api.accountsDeleteAccount).toHaveBeenCalledWith({ path: { account_id: 'a1' } })
  })
})
