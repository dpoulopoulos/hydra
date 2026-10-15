import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { BudgetProgressRow, CategoryTreeNode } from '@/api'
import { Component as BudgetsPage } from '@/pages/budgets'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    reportsBudgetProgress: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    accountsListAccounts: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR' } }),
  useIsHouseholdOwner: () => true,
}))

const api = await import('@/api')

function category(id: string, name: string, children: CategoryTreeNode[] = []) {
  return {
    id,
    name,
    household_id: 'h',
    created_at: '2026-01-01T00:00:00Z',
    children,
  } as CategoryTreeNode
}

function row(categoryId: string, name: string, parentId: string | null): BudgetProgressRow {
  return {
    budget_id: `budget-${categoryId}`,
    category_id: categoryId,
    category_name: name,
    parent_id: parentId,
    covers_subcategories: false,
    limit_minor: 10000,
    spent_minor: 5000,
    remaining_minor: 5000,
    progress: 0.5,
    is_over_budget: false,
  }
}

function renderPage(rows: BudgetProgressRow[]) {
  vi.mocked(api.reportsBudgetProgress).mockResolvedValue({
    data: {
      period: {},
      total_limit_minor: 0,
      total_spent_minor: 0,
      total_remaining_minor: 0,
      rows,
      unbudgeted_spend_minor: 0,
    },
  } as never)

  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <BudgetsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({ data: { data: [], count: 0 } } as never)
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: {
      data: [
        category('food', 'Food', [category('groceries', 'Groceries')]),
        category('home', 'Home', [category('rent', 'Rent')]),
        category('transport', 'Transport'),
      ],
    },
  } as never)
})

describe('folding a parent over its subcategories', () => {
  it('shows the subcategories until the parent is folded shut', async () => {
    const user = userEvent.setup()
    renderPage([row('groceries', 'Groceries', 'food')])

    // Open at first: nothing is hidden until it is asked for.
    const hide = await screen.findByRole('button', { name: 'Hide the subcategories of Food' })
    expect(screen.getByText('Groceries')).toBeInTheDocument()

    await user.click(hide)
    expect(screen.queryByText('Groceries')).not.toBeInTheDocument()
    expect(screen.getByText('Food')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Show the subcategories of Food' }))
    expect(screen.getByText('Groceries')).toBeInTheDocument()
  })

  it('folds and unfolds every parent at once', async () => {
    const user = userEvent.setup()
    renderPage([row('groceries', 'Groceries', 'food'), row('rent', 'Rent', 'home')])

    await user.click(await screen.findByRole('button', { name: 'Collapse all' }))
    expect(screen.queryByText('Groceries')).not.toBeInTheDocument()
    expect(screen.queryByText('Rent')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Expand all' }))
    expect(screen.getByText('Groceries')).toBeInTheDocument()
    expect(screen.getByText('Rent')).toBeInTheDocument()
  })

  it('offers to expand all once each parent is folded by hand', async () => {
    const user = userEvent.setup()
    renderPage([row('groceries', 'Groceries', 'food'), row('rent', 'Rent', 'home')])

    await user.click(await screen.findByRole('button', { name: 'Hide the subcategories of Food' }))
    expect(screen.getByRole('button', { name: 'Collapse all' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Hide the subcategories of Home' }))
    expect(screen.getByRole('button', { name: 'Expand all' })).toBeInTheDocument()
  })

  it('offers no fold-all button when no budget sits under a parent', async () => {
    renderPage([row('transport', 'Transport', null)])

    expect(await screen.findByText('Transport')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Collapse all' })).not.toBeInTheDocument()
  })
})
