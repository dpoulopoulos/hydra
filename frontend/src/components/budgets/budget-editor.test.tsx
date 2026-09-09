import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BudgetPublic } from '@/api'
import { BudgetEditor } from '@/components/budgets/budget-editor'

// The dialog talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks: what matters here is
// the payload that reaches `PUT /budgets/bulk`, which replaces the whole month.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    budgetsListBudgets: vi.fn(),
    budgetsBulkUpsertBudgets: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

// Stubbed so the toast a failed save raises can be asserted: the editor is
// covered by the confirmation at that point, so the toast is the only place
// the message shows.
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const api = await import('@/api')
const { toast } = await import('sonner')

const MONTH = '2026-03'
const GROCERIES = '11111111-1111-1111-1111-111111111111'
const TRANSPORT = '22222222-2222-2222-2222-222222222222'

function category(id: string, name: string) {
  return { id, name, household_id: 'h', created_at: '2026-01-01T00:00:00Z', children: [] }
}

function budget(categoryId: string, limitMinor: number): BudgetPublic {
  return {
    id: `budget-${categoryId}`,
    household_id: 'h',
    category_id: categoryId,
    month: `${MONTH}-01`,
    limit_minor: limitMinor,
    created_at: '2026-01-01T00:00:00Z',
  }
}

/** The saved month the API answers with, unless a test overrides the call. */
function budgetsAre(budgets: BudgetPublic[]) {
  vi.mocked(api.budgetsListBudgets).mockResolvedValue({
    data: { data: budgets, count: budgets.length },
  } as never)
}

function Harness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button onClick={() => setOpen(true)}>Reopen</button>
      <BudgetEditor open={open} month={MONTH} onOpenChange={setOpen} />
    </>
  )
}

function renderEditor() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
}

/** The field for a category, once the dialog has painted the saved figures. */
function limitField(name: string) {
  return screen.getByLabelText(name)
}

/** Agree to the confirmation a save shows when it would remove limits. */
async function confirmRemoval(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Remove and save' }))
}

beforeEach(() => {
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: {
      data: [category(GROCERIES, 'Groceries'), category(TRANSPORT, 'Transport')],
      count: 2,
    },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.budgetsBulkUpsertBudgets).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  budgetsAre([budget(GROCERIES, 30000), budget(TRANSPORT, 10000)])
})

describe('loading the month', () => {
  it('offers nothing to save while the saved limits are still on the way', async () => {
    vi.mocked(api.budgetsListBudgets).mockReturnValue(new Promise(() => {}) as never)
    renderEditor()

    expect(await screen.findByText('Budgets for March 2026')).toBeInTheDocument()
    expect(screen.queryByLabelText('Groceries')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save budgets' })).not.toBeInTheDocument()
  })

  it('offers nothing to save when the saved limits failed to load', async () => {
    vi.mocked(api.budgetsListBudgets).mockResolvedValue({
      error: { detail: 'Budgets are unavailable.' },
    } as never)
    renderEditor()

    expect(await screen.findByText('Budgets are unavailable.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Groceries')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save budgets' })).not.toBeInTheDocument()
  })
})

describe('saving', () => {
  /** The entries the last save sent to the bulk endpoint. */
  function sentEntries() {
    const call = vi.mocked(api.budgetsBulkUpsertBudgets).mock.calls.at(-1)
    return (call?.[0] as { body: { entries: unknown[] } }).body.entries
  }

  it('reads an amount typed with a thousands space rather than dropping it', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.type(limitField('Groceries'), '1 000')
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    await vi.waitFor(() => expect(api.budgetsBulkUpsertBudgets).toHaveBeenCalled())
    expect(sentEntries()).toEqual([
      { category_id: GROCERIES, limit_minor: 100000 },
      { category_id: TRANSPORT, limit_minor: 10000 },
    ])
  })

  it('reports an amount it cannot read instead of deleting that budget', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.type(limitField('Groceries'), 'abc')
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    expect(await screen.findByText('Enter a number.')).toBeInTheDocument()
    expect(limitField('Groceries')).toBeInvalid()
    expect(api.budgetsBulkUpsertBudgets).not.toHaveBeenCalled()
  })

  it('clears the complaint once the amount is retyped', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.type(limitField('Groceries'), 'abc')
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    expect(await screen.findByText('Enter a number.')).toBeInTheDocument()

    await user.clear(limitField('Groceries'))
    await user.type(limitField('Groceries'), '250')

    expect(screen.queryByText('Enter a number.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await vi.waitFor(() => expect(api.budgetsBulkUpsertBudgets).toHaveBeenCalled())
    expect(sentEntries()).toEqual([
      { category_id: GROCERIES, limit_minor: 25000 },
      { category_id: TRANSPORT, limit_minor: 10000 },
    ])
  })

  it('drops the edits once they are saved, so the next save starts from the month', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await confirmRemoval(user)
    await vi.waitFor(() => expect(api.budgetsBulkUpsertBudgets).toHaveBeenCalled())

    // The month has moved on since: whatever it holds now is what a reopened
    // dialog edits, not the emptied field from the save before.
    budgetsAre([budget(GROCERIES, 30000), budget(TRANSPORT, 10000)])
    await user.click(screen.getByRole('button', { name: 'Reopen' }))
    expect(await screen.findByLabelText('Groceries')).toHaveValue('300')

    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await vi.waitFor(() => expect(api.budgetsBulkUpsertBudgets).toHaveBeenCalledTimes(2))
    expect(sentEntries()).toEqual([
      { category_id: GROCERIES, limit_minor: 30000 },
      { category_id: TRANSPORT, limit_minor: 10000 },
    ])
  })

  it('still un-budgets a category whose field was emptied on purpose', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await confirmRemoval(user)

    await vi.waitFor(() => expect(api.budgetsBulkUpsertBudgets).toHaveBeenCalled())
    expect(sentEntries()).toEqual([{ category_id: TRANSPORT, limit_minor: 10000 }])
  })
})

describe('confirming what a save removes', () => {
  /** The entries the last save sent to the bulk endpoint. */
  function sentEntries() {
    const call = vi.mocked(api.budgetsBulkUpsertBudgets).mock.calls.at(-1)
    return (call?.[0] as { body: { entries: unknown[] } }).body.entries
  }

  it('names the category about to lose its limit, and sends nothing yet', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    expect(await screen.findByText('Stop budgeting Groceries?')).toBeInTheDocument()
    expect(api.budgetsBulkUpsertBudgets).not.toHaveBeenCalled()
  })

  it('names every category, when several fields were emptied', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.clear(limitField('Transport'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    expect(await screen.findByText('Stop budgeting 2 categories?')).toBeInTheDocument()
    expect(screen.getByText('Groceries, Transport')).toBeInTheDocument()
  })

  it('counts a limit zeroed out, since a zero limit is not budgeted either', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.type(limitField('Groceries'), '0')
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    expect(await screen.findByText('Stop budgeting Groceries?')).toBeInTheDocument()
  })

  it('leaves the month alone when the confirmation is turned down', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await user.click(await screen.findByRole('button', { name: 'Keep it' }))

    expect(api.budgetsBulkUpsertBudgets).not.toHaveBeenCalled()
    // The editor is still open on the emptied field, so the save can be
    // finished or the amount typed back in.
    expect(limitField('Groceries')).toHaveValue('')
  })

  it('asks nothing when every budgeted category keeps a limit', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.type(limitField('Groceries'), '250')
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    await vi.waitFor(() => expect(api.budgetsBulkUpsertBudgets).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: 'Remove and save' })).not.toBeInTheDocument()
    expect(sentEntries()).toEqual([
      { category_id: GROCERIES, limit_minor: 25000 },
      { category_id: TRANSPORT, limit_minor: 10000 },
    ])
  })

  it('reports a failed save in a toast, since the confirmation covers the editor', async () => {
    vi.mocked(api.budgetsBulkUpsertBudgets).mockResolvedValue({
      error: { detail: 'Budgets are unavailable.' },
    } as never)
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await confirmRemoval(user)

    await vi.waitFor(() => expect(toast.error).toHaveBeenCalledWith('Budgets are unavailable.'))
    // Nothing was removed, so the editor keeps the edits and the save can be
    // tried again.
    expect(screen.getByRole('button', { name: 'Remove and save' })).toBeInTheDocument()
  })

  it('asks again on the next save, rather than remembering the last answer', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))
    await user.click(await screen.findByRole('button', { name: 'Keep it' }))
    await user.click(screen.getByRole('button', { name: 'Save budgets' }))

    expect(await screen.findByText('Stop budgeting Groceries?')).toBeInTheDocument()
  })
})

describe('cancelling', () => {
  it('drops the edits, so a reopened dialog shows the saved limits', async () => {
    const user = userEvent.setup()
    renderEditor()

    await user.clear(await screen.findByLabelText('Groceries'))
    await user.type(limitField('Groceries'), '999')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    await user.click(screen.getByRole('button', { name: 'Reopen' }))

    expect(await screen.findByLabelText('Groceries')).toHaveValue('300')
  })
})
