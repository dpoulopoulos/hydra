import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { TransactionFilters } from '@/components/transactions/transaction-filters'
import { emptyFilters } from '@/lib/transaction-filters'

// The filters fill two of their pickers from the API, so the tests stand in for
// the endpoints: what matters here is what a picker says when its list never
// arrives, since a filter row offering nothing looks like a household with
// nothing to filter by.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
  }
})

const api = await import('@/api')

function renderFilters() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <TransactionFilters
        filters={emptyFilters}
        onChange={() => {}}
        pageSize={30}
        onPageSizeChange={() => {}}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: [{ id: 'a', name: 'Current' }], count: 1 },
  } as never)
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: { data: [{ id: 'c', name: 'Groceries', children: [] }], count: 1 },
  } as never)
})

describe('a filter whose list will not load', () => {
  it('says why the account filter has nothing to offer', async () => {
    vi.mocked(api.accountsListAccounts).mockResolvedValue({
      error: { detail: 'Accounts are down.' },
    } as never)
    renderFilters()

    expect(
      await screen.findByText('Could not load your accounts. Accounts are down.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Account' })).toBeDisabled()
  })

  it('says why the category filter has nothing to offer', async () => {
    vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
      error: { detail: 'Categories are down.' },
    } as never)
    renderFilters()

    expect(
      await screen.findByText('Could not load your categories. Categories are down.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Category' })).toBeDisabled()
  })

  it('leaves the rest of the row usable', async () => {
    vi.mocked(api.accountsListAccounts).mockResolvedValue({
      error: { detail: 'Accounts are down.' },
    } as never)
    renderFilters()

    await screen.findByText('Could not load your accounts. Accounts are down.')
    expect(screen.getByRole('combobox', { name: 'Kind' })).toBeEnabled()
    expect(screen.getByRole('combobox', { name: 'Category' })).toBeEnabled()
  })

  it('leaves both pickers alone when the lists arrive', async () => {
    renderFilters()

    const account = await screen.findByRole('combobox', { name: 'Account' })
    expect(account).toBeEnabled()
    expect(screen.queryByText(/Could not load/)).not.toBeInTheDocument()
  })
})
