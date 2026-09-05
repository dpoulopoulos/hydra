import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AccountPublic } from '@/api'
import { AccountDialog } from '@/components/accounts/account-dialog'

// The dialog calls the generated client directly, so the endpoints are what the
// test stands in for: what matters is the type the picker shows and the type
// the save carries.
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

function renderDialog(account: AccountPublic | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <AccountDialog open account={account} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The body the last create call sent. */
function createdBody() {
  const call = vi.mocked(api.accountsCreateAccount).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

beforeEach(() => {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.accountsCreateAccount).mockResolvedValue({ data: {} } as never)
  vi.mocked(api.accountsUpdateAccount).mockResolvedValue({ data: {} } as never)
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
