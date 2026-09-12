import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BudgetPublic } from '@/api'
import { CopyMonthDialog } from '@/components/budgets/copy-month-dialog'

// The dialog talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks: what matters here is
// what the user is told before `POST /budgets/copy` goes out with a replace,
// which deletes a limit the source month does not set.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    budgetsCopyBudgets: vi.fn(),
    budgetsListBudgets: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
  }
})

const api = await import('@/api')

const MONTH = '2026-09'
const SOURCE = '2026-08'
const GROCERIES = '11111111-1111-1111-1111-111111111111'
const TRANSPORT = '22222222-2222-2222-2222-222222222222'
const RETIRED = '33333333-3333-3333-3333-333333333333'

function category(id: string, name: string) {
  return { id, name, household_id: 'h', created_at: '2026-01-01T00:00:00Z', children: [] }
}

function budget(month: string, categoryId: string): BudgetPublic {
  return {
    id: `budget-${month}-${categoryId}`,
    household_id: 'h',
    category_id: categoryId,
    month: `${month}-01`,
    limit_minor: 30000,
    created_at: '2026-01-01T00:00:00Z',
  }
}

/** What each month answers with, by month key. */
function budgetsAre(months: Record<string, BudgetPublic[]>) {
  vi.mocked(api.budgetsListBudgets).mockImplementation((options) => {
    const month = (options as { query: { month: string } }).query.month
    const data = months[month] ?? []
    return Promise.resolve({ data: { data, count: data.length } }) as never
  })
}

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const view = (open: boolean) => (
    <QueryClientProvider client={client}>
      <CopyMonthDialog open={open} month={MONTH} onOpenChange={() => {}} />
    </QueryClientProvider>
  )
  const rendered = render(view(true))
  return {
    ...rendered,
    client,
    /** Close the dialog and open it again, as a second try would. */
    reopen: () => {
      rendered.rerender(view(false))
      rendered.rerender(view(true))
    },
  }
}

/** The body the last copy call sent. */
function copiedBody() {
  const call = vi.mocked(api.budgetsCopyBudgets).mock.calls.at(-1)
  return (call?.[0] as { body: unknown }).body
}

/** Tick "Replace the limits already set". */
async function replaceLimits(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByLabelText('Replace the limits already set'))
}

/** Ask for the copy, once the dialog will take it. */
async function copyBudgets(user: ReturnType<typeof userEvent.setup>) {
  const button = await screen.findByRole('button', { name: 'Copy budgets' })
  await vi.waitFor(() => expect(button).toBeEnabled())
  await user.click(button)
}

beforeEach(() => {
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: {
      data: [category(GROCERIES, 'Groceries'), category(TRANSPORT, 'Transport')],
      count: 2,
    },
  } as never)
  vi.mocked(api.budgetsCopyBudgets).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  budgetsAre({ [SOURCE]: [budget(SOURCE, GROCERIES)], [MONTH]: [budget(MONTH, TRANSPORT)] })
})

describe('copying without replacing', () => {
  it('sends the copy without asking, since nothing is removed', async () => {
    const user = userEvent.setup()
    renderDialog()

    await copyBudgets(user)

    expect(copiedBody()).toEqual({ from_month: SOURCE, to_month: MONTH, overwrite: false })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})

describe('replacing the limits already set', () => {
  it('names the categories the replace leaves unbudgeted, and waits', async () => {
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)
    await copyBudgets(user)

    expect(await screen.findByText('Stop budgeting Transport?')).toBeInTheDocument()
    expect(api.budgetsCopyBudgets).not.toHaveBeenCalled()
  })

  it('counts them when there is more than one', async () => {
    budgetsAre({
      [SOURCE]: [],
      [MONTH]: [budget(MONTH, GROCERIES), budget(MONTH, TRANSPORT)],
    })
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)
    await copyBudgets(user)

    expect(await screen.findByText('Stop budgeting 2 categories?')).toBeInTheDocument()
    expect(await screen.findByText('Groceries, Transport')).toBeInTheDocument()
  })

  it('sends the copy once the removals are agreed to', async () => {
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)
    await copyBudgets(user)
    await user.click(await screen.findByRole('button', { name: 'Remove and copy' }))

    expect(copiedBody()).toEqual({ from_month: SOURCE, to_month: MONTH, overwrite: true })
  })

  it('sends nothing when the removals are turned down', async () => {
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)
    await copyBudgets(user)
    await user.click(await screen.findByRole('button', { name: 'Keep it' }))

    expect(api.budgetsCopyBudgets).not.toHaveBeenCalled()
  })

  it('does not ask when the source month sets every limit this one has', async () => {
    budgetsAre({
      [SOURCE]: [budget(SOURCE, GROCERIES), budget(SOURCE, TRANSPORT)],
      [MONTH]: [budget(MONTH, TRANSPORT)],
    })
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)
    await copyBudgets(user)

    expect(copiedBody()).toEqual({ from_month: SOURCE, to_month: MONTH, overwrite: true })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  // The tree is asked for the archived ones as well, and their limits go the
  // same way as any other, so the list has to be able to call them by name.
  it('names an archived category the replace leaves unbudgeted', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
      data: {
        data: [category(GROCERIES, 'Groceries'), category(RETIRED, 'Piano lessons')],
        count: 2,
      },
    } as never)
    budgetsAre({ [SOURCE]: [budget(SOURCE, GROCERIES)], [MONTH]: [budget(MONTH, RETIRED)] })
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)
    await copyBudgets(user)

    expect(await screen.findByText('Stop budgeting Piano lessons?')).toBeInTheDocument()
    expect(vi.mocked(api.categoriesGetCategoryTree).mock.calls.at(-1)?.[0]).toMatchObject({
      query: { include_archived: true },
    })
  })

  it('describes the month picked from, not the one it opened on', async () => {
    budgetsAre({ '2026-07': [], [MONTH]: [budget(MONTH, GROCERIES)] })
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByLabelText('Copy from'))
    await user.click(await screen.findByRole('option', { name: 'July 2026' }))
    await replaceLimits(user)
    await copyBudgets(user)

    expect(await screen.findByText('Stop budgeting Groceries?')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Remove and copy' }))
    expect(copiedBody()).toEqual({ from_month: '2026-07', to_month: MONTH, overwrite: true })
  })
})

describe('when what the removals are read from does not load', () => {
  it('holds a replace back while they are still on the way', async () => {
    vi.mocked(api.budgetsListBudgets).mockReturnValue(new Promise(() => {}) as never)
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)

    expect(screen.getByRole('button', { name: 'Copy budgets' })).toBeDisabled()
  })

  it('refuses a replace it cannot describe, and says why', async () => {
    vi.mocked(api.budgetsListBudgets).mockResolvedValue({
      error: { detail: 'Budgets are unavailable.' },
    } as never)
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)

    expect(await screen.findByText(/did not load/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy budgets' })).toBeDisabled()
  })

  it('holds a replace back while the category tree is still on the way', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockReturnValue(new Promise(() => {}) as never)
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)

    expect(screen.getByRole('button', { name: 'Copy budgets' })).toBeDisabled()
  })

  // Without the names, `removedLimits` has nothing to match the ids against and
  // comes back empty, which would send the replace as if it removed nothing.
  it('refuses a replace when the category tree fails', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
      error: { detail: 'Categories are unavailable.' },
    } as never)
    const user = userEvent.setup()
    renderDialog()

    await replaceLimits(user)

    expect(await screen.findByText(/did not load/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy budgets' })).toBeDisabled()
    expect(api.budgetsCopyBudgets).not.toHaveBeenCalled()
  })

  // What is in hand while a month is being fetched again is what it held
  // before, which is no basis for a list of what a replace takes away.
  it('holds a replace back while a month is being read again', async () => {
    const user = userEvent.setup()
    const { client } = renderDialog()
    const button = await screen.findByRole('button', { name: 'Copy budgets' })

    await replaceLimits(user)
    await vi.waitFor(() => expect(button).toBeEnabled())

    vi.mocked(api.budgetsListBudgets).mockReturnValue(new Promise(() => {}) as never)
    void client.invalidateQueries({ queryKey: ['budgets'] })

    await vi.waitFor(() => expect(button).toBeDisabled())
  })

  // The tree is only asked for while the dialog is open, so a failure earlier
  // in the visit is not the last word on it.
  it('asks for the category tree again when the dialog is opened again', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValueOnce({
      error: { detail: 'Categories are unavailable.' },
    } as never)
    const user = userEvent.setup()
    const { reopen } = renderDialog()

    await replaceLimits(user)
    expect(await screen.findByText(/did not load/i)).toBeInTheDocument()

    reopen()

    await copyBudgets(user)
    expect(await screen.findByText('Stop budgeting Transport?')).toBeInTheDocument()
  })

  it('still copies without replacing', async () => {
    vi.mocked(api.budgetsListBudgets).mockResolvedValue({
      error: { detail: 'Budgets are unavailable.' },
    } as never)
    const user = userEvent.setup()
    renderDialog()

    await copyBudgets(user)

    expect(copiedBody()).toEqual({ from_month: SOURCE, to_month: MONTH, overwrite: false })
  })
})
