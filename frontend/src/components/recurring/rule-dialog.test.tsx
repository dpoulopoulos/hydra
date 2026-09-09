import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { RuleDialog } from '@/components/recurring/rule-dialog'
import { useAccounts } from '@/hooks/use-accounts'

// The dialog reads its pickers through the generated client, so the tests stand
// in for the endpoints: what matters here is what the form holds after the
// account list comes back again, which it does on every window focus.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

const api = await import('@/api')

const CURRENT = '11111111-1111-1111-1111-111111111111'
const SAVINGS = '22222222-2222-2222-2222-222222222222'

function account(id: string, name: string, balanceMinor: number) {
  return {
    id,
    name,
    type: 'current',
    household_id: 'h',
    currency_code: 'EUR',
    opening_balance_minor: 0,
    opening_balance_date: '2026-01-01',
    current_balance_minor: balanceMinor,
    created_at: '2026-01-01T00:00:00Z',
  }
}

/** The accounts the API answers with until a test replaces them. */
function accountsAre(...accounts: ReturnType<typeof account>[]) {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: accounts, count: accounts.length },
  } as never)
}

/**
 * The balance the account list currently holds, painted next to the dialog.
 *
 * A refetch lands asynchronously, so a test needs somewhere to watch for it:
 * without this it would assert on the form before the fresh payload had
 * reached the dialog at all, and pass whatever the dialog did with it.
 */
function Balance() {
  const { data } = useAccounts()
  return <span data-testid="balance">{data?.data[0]?.current_balance_minor}</span>
}

function Harness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button onClick={() => setOpen(true)}>Reopen</button>
      <Balance />
      <RuleDialog open={open} rule={null} onOpenChange={setOpen} />
    </>
  )
}

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
  return client
}

/** A refetch of the account list, the way returning to the tab triggers one. */
async function accountsRefetch(client: QueryClient, balanceMinor: number) {
  await act(async () => {
    await client.refetchQueries({ queryKey: ['accounts'] })
  })
  await vi.waitFor(() =>
    expect(screen.getByTestId('balance')).toHaveTextContent(String(balanceMinor)),
  )
}

/** The account the picker currently shows. */
function chosenAccount() {
  return screen.getByRole('combobox', { name: 'Account' }).textContent
}

beforeEach(() => {
  accountsAre(account(CURRENT, 'Current', 50000), account(SAVINGS, 'Savings', 900000))
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
})

describe('a background account refetch', () => {
  it('leaves what the user has typed alone', async () => {
    const user = userEvent.setup()
    const client = renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Rent')
    await user.type(screen.getByLabelText('Amount'), '850')
    await user.type(screen.getByLabelText('On day'), '1')

    // A balance is derived from the ledger, so any transaction in the household
    // changes it and the payload comes back as a fresh object.
    accountsAre(account(CURRENT, 'Current', 43000), account(SAVINGS, 'Savings', 900000))
    await accountsRefetch(client, 43000)

    expect(screen.getByLabelText('Name')).toHaveValue('Rent')
    expect(screen.getByLabelText('Amount')).toHaveValue('850')
    expect(screen.getByLabelText('On day')).toHaveValue(1)
  })

  it('leaves the advanced section open with the fields typed into it', async () => {
    const user = userEvent.setup()
    const client = renderDialog()

    await user.click(await screen.findByRole('button', { name: 'More options' }))
    await user.type(screen.getByLabelText('Merchant'), 'Landlord')

    accountsAre(account(CURRENT, 'Current', 43000), account(SAVINGS, 'Savings', 900000))
    await accountsRefetch(client, 43000)

    expect(screen.getByRole('button', { name: 'More options' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByLabelText('Merchant')).toHaveValue('Landlord')
  })

  it('leaves the account the user chose alone', async () => {
    const user = userEvent.setup()
    const client = renderDialog()

    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
    await user.click(screen.getByRole('combobox', { name: 'Account' }))
    await user.click(await screen.findByRole('option', { name: 'Savings' }))
    expect(chosenAccount()).toBe('Savings')

    accountsAre(account(CURRENT, 'Current', 43000), account(SAVINGS, 'Savings', 900000))
    await accountsRefetch(client, 43000)

    expect(chosenAccount()).toBe('Savings')
  })
})

describe('seeding the form', () => {
  it('chooses the first account once the list arrives', async () => {
    let deliver: (payload: unknown) => void = () => {}
    vi.mocked(api.accountsListAccounts).mockReturnValue(
      new Promise((resolve) => {
        deliver = resolve
      }) as never,
    )
    renderDialog()

    expect(await screen.findByLabelText('Name')).toBeInTheDocument()
    expect(chosenAccount()).toBe('Choose an account')

    await act(async () => {
      deliver({ data: { data: [account(CURRENT, 'Current', 50000)], count: 1 } })
    })

    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
  })

  it('keeps what the user typed while the list is still on the way', async () => {
    const user = userEvent.setup()
    let deliver: (payload: unknown) => void = () => {}
    vi.mocked(api.accountsListAccounts).mockReturnValue(
      new Promise((resolve) => {
        deliver = resolve
      }) as never,
    )
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Rent')

    await act(async () => {
      deliver({ data: { data: [account(CURRENT, 'Current', 50000)], count: 1 } })
    })

    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
    expect(screen.getByLabelText('Name')).toHaveValue('Rent')
  })

  it('starts empty again when the dialog is reopened', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Rent')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Reopen' }))

    expect(await screen.findByLabelText('Name')).toHaveValue('')
    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
  })
})

describe('a picker whose list will not load', () => {
  it('says why the account picker has nothing to offer', async () => {
    vi.mocked(api.accountsListAccounts).mockResolvedValue({
      error: { detail: 'Accounts are down.' },
    } as never)
    renderDialog()

    expect(
      await screen.findByText('Could not load your accounts. Accounts are down.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Account' })).toBeDisabled()
  })

  it('says why the category picker has nothing to offer', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
      error: { detail: 'Categories are down.' },
    } as never)
    renderDialog()

    expect(
      await screen.findByText('Could not load your categories. Categories are down.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Category' })).toBeDisabled()
  })

  it('leaves the pickers alone when both lists arrive', async () => {
    renderDialog()

    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Category' })).toBeEnabled()
  })
})
