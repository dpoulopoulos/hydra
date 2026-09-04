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

const api = await import('@/api')

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
