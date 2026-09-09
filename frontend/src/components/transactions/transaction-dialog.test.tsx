import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TransactionPublic } from '@/api'
import { TransactionDialog } from '@/components/transactions/transaction-dialog'
import { useAccounts } from '@/hooks/use-accounts'

// The dialog reads its pickers through the generated client, so the tests stand
// in for the endpoints: what matters here is what the form holds after the
// account list comes back again, which it does on every window focus, and the
// amount that reaches the API, which the household's currency decides.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
    transactionsUpdateTransaction: vi.fn(),
    transactionsCreateTransaction: vi.fn(),
  }
})

const api = await import('@/api')

const CURRENT = '11111111-1111-1111-1111-111111111111'
const SAVINGS = '22222222-2222-2222-2222-222222222222'

function account(id: string, name: string, balanceMinor: number, currencyCode = 'EUR') {
  return {
    id,
    name,
    type: 'current',
    household_id: 'h',
    currency_code: currencyCode,
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

/** The household the dialog reads its currency from. */
function householdSpends(currency: string) {
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: currency },
  } as never)
}

function transaction(amountMinor: number): TransactionPublic {
  return {
    id: 'transaction',
    household_id: 'h',
    account_id: CURRENT,
    counter_account_id: null,
    category_id: null,
    kind: 'expense',
    amount_minor: amountMinor,
    occurred_on: '2026-03-04',
    merchant: null,
    note: null,
    created_at: '2026-03-04T00:00:00Z',
  } as TransactionPublic
}

/** The currency the amount field says it is in. */
function amountCurrency() {
  return screen.getByLabelText('Amount').previousSibling?.textContent
}

/** The amount the last save sent to the API. */
function sentAmountMinor() {
  const call = vi.mocked(api.transactionsUpdateTransaction).mock.calls.at(-1)
  return (call?.[0] as { body: { amount_minor: number } }).body.amount_minor
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
      <TransactionDialog open={open} transaction={null} onOpenChange={setOpen} />
    </>
  )
}

function withClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
  return client
}

function renderDialog() {
  return withClient(<Harness />)
}

/** The dialog opened on a transaction that already exists. */
function renderEditDialog(existing: TransactionPublic) {
  return withClient(<TransactionDialog open transaction={existing} onOpenChange={() => {}} />)
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
  vi.mocked(api.transactionsUpdateTransaction).mockResolvedValue({ data: {} } as never)
  householdSpends('EUR')
})

describe('a background account refetch', () => {
  it('leaves what the user has typed alone', async () => {
    const user = userEvent.setup()
    const client = renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '45.90')
    await user.type(screen.getByLabelText('Merchant'), 'Tesco')
    await user.type(screen.getByLabelText('Note'), 'weekly shop')

    // A balance is derived from the ledger, so any transaction in the household
    // changes it and the payload comes back as a fresh object.
    accountsAre(account(CURRENT, 'Current', 43000), account(SAVINGS, 'Savings', 900000))
    await accountsRefetch(client, 43000)

    expect(screen.getByLabelText('Amount')).toHaveValue('45.90')
    expect(screen.getByLabelText('Merchant')).toHaveValue('Tesco')
    expect(screen.getByLabelText('Note')).toHaveValue('weekly shop')
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

    expect(await screen.findByLabelText('Amount')).toBeInTheDocument()
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

    await user.type(await screen.findByLabelText('Merchant'), 'Tesco')

    await act(async () => {
      deliver({ data: { data: [account(CURRENT, 'Current', 50000)], count: 1 } })
    })

    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
    expect(screen.getByLabelText('Merchant')).toHaveValue('Tesco')
  })

  it('starts empty again when the dialog is reopened', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Merchant'), 'Tesco')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Reopen' }))

    expect(await screen.findByLabelText('Merchant')).toHaveValue('')
    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
  })
})

describe('editing an amount', () => {
  it('sends back what a two-decimal amount was opened with', async () => {
    renderEditDialog(transaction(4250))

    await waitFor(() => expect(screen.getByLabelText('Amount')).toHaveValue('42.5'))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(sentAmountMinor()).toBe(4250))
  })

  it('sends back what a zero-decimal amount was opened with', async () => {
    accountsAre(account(CURRENT, 'Current', 50000, 'JPY'))
    renderEditDialog(transaction(1000))

    await waitFor(() => expect(screen.getByLabelText('Amount')).toHaveValue('1000'))
    await userEvent.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(sentAmountMinor()).toBe(1000))
  })
})

describe('a picker whose list will not load', () => {
  /** The API refusing to list the accounts. */
  function accountsFail(detail: string) {
    vi.mocked(api.accountsListAccounts).mockResolvedValue({ error: { detail } } as never)
  }

  /** The API refusing to hand over the category tree. */
  function categoriesFail(detail: string) {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({ error: { detail } } as never)
  }

  it('says why the account picker has nothing to offer', async () => {
    accountsFail('Accounts are down.')
    renderDialog()

    expect(
      await screen.findByText('Could not load your accounts. Accounts are down.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Account' })).toBeDisabled()
  })

  it('says why the category picker has nothing to offer', async () => {
    categoriesFail('Categories are down.')
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

const GROCERIES = '33333333-3333-3333-3333-333333333333'

/**
 * A household whose pickers have something to offer: a second account to move
 * money to, and a category to file the spending under.
 */
function pickersAreStocked() {
  accountsAre(account(CURRENT, 'Current', 50000), account(SAVINGS, 'Rainy day', 900000))
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: {
      data: [
        {
          id: GROCERIES,
          name: 'Groceries',
          kind: 'expense',
          household_id: 'h',
          created_at: '2026-01-01T00:00:00Z',
          children: [],
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.transactionsCreateTransaction).mockResolvedValue({ data: {} } as never)
}

/** The body the last create call sent. */
function createdBody() {
  const call = vi.mocked(api.transactionsCreateTransaction).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

describe('recording an expense', () => {
  beforeEach(pickersAreStocked)

  it('saves the account and category that were picked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '12.50')
    await user.click(await screen.findByRole('combobox', { name: 'Account' }))
    await user.click(await screen.findByRole('option', { name: 'Rainy day' }))

    expect(screen.getByRole('combobox', { name: 'Account' })).toHaveTextContent('Rainy day')

    await user.click(screen.getByRole('combobox', { name: 'Category' }))
    await user.click(await screen.findByRole('option', { name: 'Groceries' }))

    expect(screen.getByRole('combobox', { name: 'Category' })).toHaveTextContent('Groceries')

    await user.click(screen.getByRole('button', { name: 'Record it' }))

    await waitFor(() => expect(api.transactionsCreateTransaction).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({
      kind: 'expense',
      amount_minor: 1250,
      account_id: SAVINGS,
      category_id: GROCERIES,
      counter_account_id: null,
    })
  })
})

describe('recording a transfer', () => {
  beforeEach(pickersAreStocked)

  it('keeps the account the money leaves out of the destinations', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('tab', { name: 'Transfer' }))
    await user.click(await screen.findByRole('combobox', { name: 'To account' }))

    expect(await screen.findByRole('option', { name: 'Rainy day' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Current' })).not.toBeInTheDocument()
  })

  it('saves the destination that was picked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '40')
    await user.click(screen.getByRole('tab', { name: 'Transfer' }))
    await user.click(await screen.findByRole('combobox', { name: 'To account' }))
    await user.click(await screen.findByRole('option', { name: 'Rainy day' }))

    expect(screen.getByRole('combobox', { name: 'To account' })).toHaveTextContent('Rainy day')

    await user.click(screen.getByRole('button', { name: 'Record it' }))

    await waitFor(() => expect(api.transactionsCreateTransaction).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({
      kind: 'transfer',
      account_id: CURRENT,
      counter_account_id: SAVINGS,
      category_id: null,
    })
  })
})

describe('an account with a currency of its own', () => {
  it('reads an amount already recorded in it, not in the household one', async () => {
    // The household keeps its books in euro, but this account holds yen: 1000
    // minor units is ¥1000, not €10.00.
    accountsAre(account(CURRENT, 'Current', 50000, 'JPY'))
    renderEditDialog(transaction(1000))

    await waitFor(() => expect(screen.getByLabelText('Amount')).toHaveValue('1000'))
    expect(amountCurrency()).toBe('JPY')
  })

  it('sends a typed amount as that account decides', async () => {
    accountsAre(account(CURRENT, 'Current', 50000, 'JPY'))
    const user = userEvent.setup()
    renderEditDialog(transaction(1000))

    await waitFor(() => expect(amountCurrency()).toBe('JPY'))
    await user.clear(screen.getByLabelText('Amount'))
    await user.type(screen.getByLabelText('Amount'), '2500')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(sentAmountMinor()).toBe(2500))
  })

  it('follows the account the picker moves to, keeping what was typed', async () => {
    accountsAre(account(CURRENT, 'Current', 50000), account(SAVINGS, 'Savings', 900000, 'JPY'))
    const user = userEvent.setup()
    renderDialog()

    await vi.waitFor(() => expect(chosenAccount()).toBe('Current'))
    expect(amountCurrency()).toBe('EUR')

    await user.type(await screen.findByLabelText('Amount'), '2500')
    await user.click(screen.getByRole('combobox', { name: 'Account' }))
    await user.click(await screen.findByRole('option', { name: 'Savings' }))

    await vi.waitFor(() => expect(amountCurrency()).toBe('JPY'))
    expect(screen.getByLabelText('Amount')).toHaveValue('2500')
  })
})
