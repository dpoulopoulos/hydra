import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ClientDialog } from '@/components/income/client-dialog'

// The dialog reads its accounts, categories and the household currency through
// the generated client, so the tests stand in for those endpoints. What
// matters here is the fee the dialog echoes back, which is where a user checks
// what will be saved.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

// A name and a note come from the vault, which the whole app sits under. None
// of that is what these tests are about.
vi.mock('@/hooks/use-vault', () => ({
  useVault: () => ({ status: 'unlocked', encrypt: async (value: string) => value }),
  useDecrypted: () => null,
}))

const api = await import('@/api')

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ClientDialog open client={null} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: [{ id: 'a', name: 'Everyday', archived_at: null }], count: 1 },
  } as never)
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
})

describe('the fee the dialog echoes back', () => {
  it('reads a fee typed with a thousands separator as thousands', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '1,200')

    expect(await screen.findByText(/€1,200\.00 a session/)).toBeInTheDocument()
  })

  it('says nothing about a fee it cannot read', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '1,2,3')

    expect(screen.queryByText(/a session/)).not.toBeInTheDocument()
  })
})
