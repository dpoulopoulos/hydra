import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CategoryKind, type CategoryPublic } from '@/api'
import { CategoryDialog } from '@/components/categories/category-dialog'

// The dialog calls the generated client directly, so the tests stand in for the
// endpoints. What matters here is not the payload but the caches the dialog
// drops afterwards: reports embed the category name, not just its id.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    categoriesGetCategoryTree: vi.fn(),
    categoriesCreateCategory: vi.fn(),
    categoriesUpdateCategory: vi.fn(),
  }
})

const api = await import('@/api')

const GROCERIES: CategoryPublic = {
  id: '11111111-1111-1111-1111-111111111111',
  household_id: 'h',
  name: 'Groceries',
  kind: CategoryKind.EXPENSE,
  parent_id: null,
  is_system: false,
  archived_at: null,
  created_at: '2026-01-01T00:00:00Z',
}

/** A report the user has already looked at, holding the name as it was. */
const SPEND_BY_CATEGORY = ['reports', 'spend-by-category', '2026-03', 1]

function renderDialog(category: CategoryPublic | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  client.setQueryData(SPEND_BY_CATEGORY, {
    slices: [{ category_id: GROCERIES.id, category_name: 'Groceries', total_minor: 1000 }],
  })

  render(
    <QueryClientProvider client={client}>
      <CategoryDialog open category={category} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
  return client
}

/** Whether the cached report has been marked for a refetch. */
function reportIsStale(client: QueryClient) {
  return client.getQueryState(SPEND_BY_CATEGORY)?.isInvalidated === true
}

beforeEach(() => {
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  vi.mocked(api.categoriesUpdateCategory).mockResolvedValue({ data: GROCERIES } as never)
  vi.mocked(api.categoriesCreateCategory).mockResolvedValue({ data: GROCERIES } as never)
})

describe('CategoryDialog', () => {
  it('drops the cached reports when a category is renamed', async () => {
    const user = userEvent.setup()
    const client = renderDialog(GROCERIES)

    const name = screen.getByLabelText('Name')
    await user.clear(name)
    await user.type(name, 'Food shopping')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(api.categoriesUpdateCategory).toHaveBeenCalled())
    await waitFor(() => expect(reportIsStale(client)).toBe(true))
  })

  it('drops the cached reports when a category is added', async () => {
    const user = userEvent.setup()
    const client = renderDialog(null)

    await user.type(screen.getByLabelText('Name'), 'Coffee')
    await user.click(screen.getByRole('button', { name: 'Add category' }))

    await waitFor(() => expect(api.categoriesCreateCategory).toHaveBeenCalled())
    await waitFor(() => expect(reportIsStale(client)).toBe(true))
  })
})

describe('the parent picker', () => {
  it('says why it has nothing to offer when the tree will not load', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
      error: { detail: 'Categories are down.' },
    } as never)
    renderDialog(GROCERIES)

    expect(
      await screen.findByText('Could not load your categories. Categories are down.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Sits under' })).toBeDisabled()
  })

  it('keeps its hint and stays usable when the tree arrives', async () => {
    renderDialog(GROCERIES)

    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Sits under' })).toBeEnabled())
    expect(screen.getByText('Leave as a top-level category, or file it under one.')).toBeVisible()
  })
})

describe('the kind picker', () => {
  /** A node of the category tree, shaped as the picker reads it. */
  function category(id: string, name: string, kind: string) {
    return { id, name, kind, household_id: 'h', created_at: '2026-01-01T00:00:00Z', children: [] }
  }

  /** The body the last create call sent. */
  function createdBody() {
    const call = vi.mocked(api.categoriesCreateCategory).mock.calls.at(-1)
    return (call?.[0] as { body: Record<string, unknown> }).body
  }

  // The parents on offer are what these tests turn on, so the tree the shared
  // setup leaves empty carries one category of each kind here.
  beforeEach(() => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
      data: {
        data: [category('c1', 'Home', 'expense'), category('c2', 'Salary', 'income')],
        count: 2,
      },
    } as never)
  })

  it('only offers parents of the chosen kind', async () => {
    const user = userEvent.setup()
    renderDialog(null)

    await user.click(await screen.findByRole('combobox', { name: 'Sits under' }))
    expect(await screen.findByRole('option', { name: 'Home' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Salary' })).not.toBeInTheDocument()
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('combobox', { name: 'Kind' }))
    await user.click(await screen.findByRole('option', { name: 'Income' }))

    await user.click(screen.getByRole('combobox', { name: 'Sits under' }))
    expect(await screen.findByRole('option', { name: 'Salary' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Home' })).not.toBeInTheDocument()
  })

  it('saves the kind and parent that were picked', async () => {
    const user = userEvent.setup()
    renderDialog(null)

    await user.type(await screen.findByLabelText('Name'), 'Bonus')
    await user.click(screen.getByRole('combobox', { name: 'Kind' }))
    await user.click(await screen.findByRole('option', { name: 'Income' }))

    expect(screen.getByRole('combobox', { name: 'Kind' })).toHaveTextContent('Income')

    await user.click(screen.getByRole('combobox', { name: 'Sits under' }))
    await user.click(await screen.findByRole('option', { name: 'Salary' }))
    await user.click(screen.getByRole('button', { name: 'Add category' }))

    await waitFor(() => expect(api.categoriesCreateCategory).toHaveBeenCalled())
    expect(createdBody()).toEqual({ name: 'Bonus', kind: 'income', parent_id: 'c2' })
  })
})
