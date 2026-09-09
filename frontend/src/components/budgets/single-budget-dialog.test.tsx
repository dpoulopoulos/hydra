import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BudgetProgressRow } from '@/api'
import { SingleBudgetDialog } from '@/components/budgets/single-budget-dialog'

// The dialog talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks: what matters here is
// the limit that reaches the API, in minor units.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    budgetsCreateBudget: vi.fn(),
    budgetsUpdateBudget: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

const api = await import('@/api')

const MONTH = '2026-03'
const GROCERIES = '11111111-1111-1111-1111-111111111111'

function progressRow(limitMinor: number): BudgetProgressRow {
  return {
    budget_id: 'budget-1',
    category_id: GROCERIES,
    category_name: 'Groceries',
    limit_minor: limitMinor,
    spent_minor: 0,
    remaining_minor: limitMinor,
  } as BudgetProgressRow
}

function renderDialog(row: BudgetProgressRow | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SingleBudgetDialog open month={MONTH} row={row} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The body the last create call sent. */
function createdBody() {
  const call = vi.mocked(api.budgetsCreateBudget).mock.calls.at(-1)
  return (call?.[0] as { body: unknown }).body
}

/** The body the last update call sent. */
function updatedBody() {
  const call = vi.mocked(api.budgetsUpdateBudget).mock.calls.at(-1)
  return (call?.[0] as { body: unknown }).body
}

beforeEach(() => {
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: {
      data: [
        {
          id: GROCERIES,
          name: 'Groceries',
          household_id: 'h',
          created_at: '2026-01-01T00:00:00Z',
          children: [],
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.budgetsCreateBudget).mockResolvedValue({ data: {} } as never)
  vi.mocked(api.budgetsUpdateBudget).mockResolvedValue({ data: {} } as never)
})

describe('setting a limit', () => {
  it('sends the typed amount for the chosen category, in minor units', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('combobox', { name: 'Category' }))
    await user.click(await screen.findByRole('option', { name: 'Groceries' }))
    await user.type(screen.getByLabelText('Monthly limit'), '300')
    await user.click(screen.getByRole('button', { name: 'Set limit' }))

    await vi.waitFor(() => expect(api.budgetsCreateBudget).toHaveBeenCalled())
    expect(createdBody()).toEqual({
      category_id: GROCERIES,
      month: MONTH,
      limit_minor: 30000,
    })
  })

  it('asks for a category before sending anything', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Monthly limit'), '300')
    await user.click(screen.getByRole('button', { name: 'Set limit' }))

    expect(await screen.findByText('Choose a category.')).toBeInTheDocument()
    expect(api.budgetsCreateBudget).not.toHaveBeenCalled()
  })
})

describe('changing a limit', () => {
  it('starts from the saved limit and sends the new one', async () => {
    const user = userEvent.setup()
    renderDialog(progressRow(30000))

    const field = await screen.findByLabelText('Monthly limit')
    expect(field).toHaveValue('300')

    await user.clear(field)
    await user.type(field, '250')
    await user.click(screen.getByRole('button', { name: 'Change limit' }))

    await vi.waitFor(() => expect(api.budgetsUpdateBudget).toHaveBeenCalled())
    expect(updatedBody()).toEqual({ limit_minor: 25000 })
  })
})

describe('reading the amount', () => {
  it('takes an amount typed with a thousands space', async () => {
    const user = userEvent.setup()
    renderDialog(progressRow(30000))

    const field = await screen.findByLabelText('Monthly limit')
    await user.clear(field)
    await user.type(field, '1 000')
    await user.click(screen.getByRole('button', { name: 'Change limit' }))

    await vi.waitFor(() => expect(api.budgetsUpdateBudget).toHaveBeenCalled())
    expect(updatedBody()).toEqual({ limit_minor: 100000 })
  })

  it('takes an amount typed with a comma for the decimals', async () => {
    const user = userEvent.setup()
    renderDialog(progressRow(30000))

    const field = await screen.findByLabelText('Monthly limit')
    await user.clear(field)
    await user.type(field, '42,50')
    await user.click(screen.getByRole('button', { name: 'Change limit' }))

    await vi.waitFor(() => expect(api.budgetsUpdateBudget).toHaveBeenCalled())
    expect(updatedBody()).toEqual({ limit_minor: 4250 })
  })

  it('takes a zero limit, which is what a budget of nothing means', async () => {
    const user = userEvent.setup()
    renderDialog(progressRow(30000))

    const field = await screen.findByLabelText('Monthly limit')
    await user.clear(field)
    await user.type(field, '0')
    await user.click(screen.getByRole('button', { name: 'Change limit' }))

    await vi.waitFor(() => expect(api.budgetsUpdateBudget).toHaveBeenCalled())
    expect(updatedBody()).toEqual({ limit_minor: 0 })
  })

  it('reports an amount it cannot read on the field itself', async () => {
    const user = userEvent.setup()
    renderDialog(progressRow(30000))

    const field = await screen.findByLabelText('Monthly limit')
    await user.clear(field)
    await user.type(field, 'abc')
    await user.click(screen.getByRole('button', { name: 'Change limit' }))

    expect(await screen.findByText('Enter a number.')).toBeInTheDocument()
    expect(screen.getByLabelText('Monthly limit')).toBeInvalid()
    expect(api.budgetsUpdateBudget).not.toHaveBeenCalled()
  })

  it('clears the complaint once the amount is retyped', async () => {
    const user = userEvent.setup()
    renderDialog(progressRow(30000))

    const field = await screen.findByLabelText('Monthly limit')
    await user.clear(field)
    await user.click(screen.getByRole('button', { name: 'Change limit' }))
    expect(await screen.findByText('Enter an amount.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Monthly limit'), '250')

    expect(screen.queryByText('Enter an amount.')).not.toBeInTheDocument()
  })
})
