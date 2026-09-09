import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AccountPublic } from '@/api'
import { AccountDialog } from '@/components/accounts/account-dialog'

// The dialog reads the household and writes the account through the generated
// client, so the tests stand in for both: what matters here is the type the
// picker shows and the save carries, and the currency the opening balance is
// read and checked in, which the account decides once it exists.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsCreateAccount: vi.fn(),
    accountsUpdateAccount: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

const api = await import('@/api')

const SAVINGS: AccountPublic = {
  id: 'a1',
  household_id: 'h',
  name: 'Rainy day',
  type: 'savings',
  institution: null,
  currency_code: 'EUR',
  opening_balance_minor: 50000,
  opening_balance_date: '2026-01-01',
  archived_at: null,
  created_at: '2026-01-01T00:00:00Z',
} as AccountPublic

function account(currencyCode: string, openingBalanceMinor: number): AccountPublic {
  return {
    id: 'account',
    household_id: 'h',
    name: 'Current',
    type: 'current',
    institution: null,
    iban: null,
    currency_code: currencyCode,
    opening_balance_minor: openingBalanceMinor,
    opening_balance_date: '2026-01-01',
    current_balance_minor: openingBalanceMinor,
    created_at: '2026-01-01T00:00:00Z',
  } as AccountPublic
}

/** The household the dialog opens a new account in. */
function householdSpends(currency: string) {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: currency },
  } as never)
}

function renderDialog(existing: AccountPublic | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AccountDialog open account={existing} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The body the last create call sent. */
function createdBody() {
  const call = vi.mocked(api.accountsCreateAccount).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

/** The currency the opening balance field says it is in. */
function balanceCurrency() {
  return screen.getByLabelText('Balance today').previousSibling?.textContent
}

beforeEach(() => {
  vi.mocked(api.accountsCreateAccount).mockResolvedValue({ data: {} } as never)
  vi.mocked(api.accountsUpdateAccount).mockResolvedValue({ data: {} } as never)
  householdSpends('EUR')
})

describe('the type picker', () => {
  it('opens on the type the account was saved with', async () => {
    renderDialog(SAVINGS)

    expect(await screen.findByRole('combobox', { name: 'Type' })).toHaveTextContent('Savings')
  })

  it('saves the type that was picked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(screen.getByLabelText('Name'), 'Holiday pot')
    await user.click(screen.getByRole('combobox', { name: 'Type' }))
    await user.click(await screen.findByRole('option', { name: 'Savings' }))

    expect(screen.getByRole('combobox', { name: 'Type' })).toHaveTextContent('Savings')

    await user.click(screen.getByRole('button', { name: 'Add account' }))

    await vi.waitFor(() => expect(api.accountsCreateAccount).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({ name: 'Holiday pot', type: 'savings' })
  })
})

describe('a new account', () => {
  it('asks for its opening balance in the household currency, which it opens in', async () => {
    householdSpends('JPY')
    renderDialog(null)

    await vi.waitFor(() => expect(balanceCurrency()).toBe('JPY'))
  })
})

describe('an account with a currency of its own', () => {
  it('saves an edit, rather than checking its balance against the household', async () => {
    // ¥100 trillion is a fine amount of yen and a hundred times too many cents.
    // The balance is not on screen and cannot be sent, but the form still has
    // to hold it: read in the household's currency it fails a bound the user
    // has no way to see, and the save quietly does nothing.
    const user = userEvent.setup()
    renderDialog(account('JPY', 100_000_000_000_000))

    await user.clear(await screen.findByLabelText('Name'))
    await user.type(screen.getByLabelText('Name'), 'Everyday')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await vi.waitFor(() => expect(vi.mocked(api.accountsUpdateAccount)).toHaveBeenCalled())
  })
})
