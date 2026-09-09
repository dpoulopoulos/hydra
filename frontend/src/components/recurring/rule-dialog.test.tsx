import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RecurringRulePublic } from '@/api'
import { RuleDialog } from '@/components/recurring/rule-dialog'
import { useAccounts } from '@/hooks/use-accounts'
import { formatMoney } from '@/lib/money'

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
    recurringRulesCreateRecurringRule: vi.fn(),
    recurringRulesUpdateRecurringRule: vi.fn(),
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

function rule(amountMinor: number): RecurringRulePublic {
  return {
    id: 'rule',
    household_id: 'h',
    name: 'Rent',
    kind: 'expense',
    amount_minor: amountMinor,
    frequency: 'monthly',
    interval: 1,
    day_of_month: 1,
    start_date: '2026-01-01',
    end_date: null,
    account_id: CURRENT,
    counter_account_id: null,
    category_id: null,
    merchant: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
  } as RecurringRulePublic
}

/** The currency the amount field says it is in. */
function amountCurrency() {
  return screen.getByLabelText('Amount').previousSibling?.textContent
}

/** The amount the last save sent to the API. */
function sentAmountMinor() {
  const call = vi.mocked(api.recurringRulesUpdateRecurringRule).mock.calls.at(-1)
  return (call?.[0] as { body: { amount_minor: number } }).body.amount_minor
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

/** The dialog opened on a rule that already exists. */
function renderEditDialog(existing: RecurringRulePublic) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <RuleDialog open rule={existing} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
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
  vi.mocked(api.recurringRulesUpdateRecurringRule).mockResolvedValue({ data: {} } as never)
})

describe('an account with a currency of its own', () => {
  it('reads a rule already recorded in it, not in the household one', async () => {
    // The household keeps its books in euro, but this account holds yen: 1000
    // minor units is ¥1000, not €10.00.
    accountsAre(account(CURRENT, 'Current', 50000, 'JPY'))
    renderEditDialog(rule(1000))

    await vi.waitFor(() => expect(screen.getByLabelText('Amount')).toHaveValue('1000'))
    expect(amountCurrency()).toBe('JPY')
  })

  it('says the rule back in that currency', async () => {
    accountsAre(account(CURRENT, 'Current', 50000, 'JPY'))
    renderEditDialog(rule(1000))

    await vi.waitFor(() =>
      expect(screen.getByText(new RegExp(`^${formatMoney(1000, 'JPY')} leaves`))).toBeVisible(),
    )
  })

  it('sends a typed amount as that account decides', async () => {
    accountsAre(account(CURRENT, 'Current', 50000, 'JPY'))
    const user = userEvent.setup()
    renderEditDialog(rule(1000))

    await vi.waitFor(() => expect(amountCurrency()).toBe('JPY'))
    await user.clear(screen.getByLabelText('Amount'))
    await user.type(screen.getByLabelText('Amount'), '2500')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await vi.waitFor(() => expect(sentAmountMinor()).toBe(2500))
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

const RENT = '33333333-3333-3333-3333-333333333333'

/**
 * A household whose pickers have something to offer: a second account to move
 * money to, and a category to file it under.
 */
function pickersAreStocked() {
  accountsAre(account(CURRENT, 'Current', 50000), account(SAVINGS, 'Rainy day', 900000))
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: {
      data: [
        {
          id: RENT,
          name: 'Rent',
          kind: 'expense',
          household_id: 'h',
          created_at: '2026-01-01T00:00:00Z',
          children: [],
        },
      ],
      count: 1,
    },
  } as never)
}

/** The body the last create call sent. */
function createdBody() {
  const call = vi.mocked(api.recurringRulesCreateRecurringRule).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

describe('the sentence under the fields', () => {
  beforeEach(pickersAreStocked)

  it('says back what every field holds, as they are filled in', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '900')
    expect(await screen.findByText(/€900.00 leaves Current every month/)).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Repeats' }))
    await user.click(await screen.findByRole('option', { name: 'Weekly' }))
    expect(await screen.findByText(/every week/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /More options/ }))
    await user.clear(await screen.findByLabelText('Every'))
    await user.type(screen.getByLabelText('Every'), '2')
    expect(await screen.findByText(/every 2 weeks/)).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'Category' }))
    await user.click(await screen.findByRole('option', { name: 'Rent' }))
    expect(await screen.findByText(/Filed under Rent\./)).toBeInTheDocument()
  })

  it('reads an amount typed with a thousands separator as thousands', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '1,200')

    expect(await screen.findByText(/€1,200\.00 leaves Current/)).toBeInTheDocument()
  })

  it('says nothing about an amount it cannot read', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '1,2,3')

    expect(screen.queryByText(/leaves/)).not.toBeInTheDocument()
  })

  it('names both accounts of a transfer', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Amount'), '50')
    await user.click(screen.getByRole('tab', { name: 'Transfer' }))
    await user.click(await screen.findByRole('combobox', { name: 'To account' }))
    await user.click(await screen.findByRole('option', { name: 'Rainy day' }))

    expect(
      await screen.findByText(/€50.00 moves from Current to Rainy day every month/),
    ).toBeInTheDocument()
  })
})

describe('saving a rule', () => {
  beforeEach(() => {
    pickersAreStocked()
    vi.mocked(api.recurringRulesCreateRecurringRule).mockResolvedValue({ data: {} } as never)
  })

  it('carries the account, category and schedule that were picked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Rent')
    await user.type(screen.getByLabelText('Amount'), '900')

    await user.click(screen.getByRole('combobox', { name: 'Account' }))
    await user.click(await screen.findByRole('option', { name: 'Rainy day' }))
    expect(screen.getByRole('combobox', { name: 'Account' })).toHaveTextContent('Rainy day')

    await user.click(screen.getByRole('combobox', { name: 'Category' }))
    await user.click(await screen.findByRole('option', { name: 'Rent' }))
    expect(screen.getByRole('combobox', { name: 'Category' })).toHaveTextContent('Rent')

    await user.type(screen.getByLabelText('On day'), '5')
    await user.click(screen.getByRole('button', { name: 'Add rule' }))

    await vi.waitFor(() => expect(api.recurringRulesCreateRecurringRule).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({
      name: 'Rent',
      kind: 'expense',
      amount_minor: 90000,
      frequency: 'monthly',
      interval: 1,
      day_of_month: 5,
      account_id: SAVINGS,
      category_id: RENT,
      counter_account_id: null,
    })
  })

  it('keeps the account the money leaves out of the destinations', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('tab', { name: 'Transfer' }))
    await user.click(await screen.findByRole('combobox', { name: 'To account' }))

    expect(await screen.findByRole('option', { name: 'Rainy day' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Current' })).not.toBeInTheDocument()
  })
})
