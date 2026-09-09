import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAccountCurrency } from '@/hooks/use-accounts'

// The hook answers from the two lists the app already caches, so the tests
// stand in for those endpoints and watch which of them the answer comes from.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

const api = await import('@/api')

const CURRENT = '11111111-1111-1111-1111-111111111111'

function account(id: string, currencyCode: string) {
  return {
    id,
    name: 'Current',
    type: 'current',
    household_id: 'h',
    currency_code: currencyCode,
    opening_balance_minor: 0,
    opening_balance_date: '2026-01-01',
    current_balance_minor: 0,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function accountsAre(...accounts: ReturnType<typeof account>[]) {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: accounts, count: accounts.length },
  } as never)
}

function renderCurrency(accountId: string | null | undefined) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderHook(() => useAccountCurrency()(accountId), {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  })
}

beforeEach(() => {
  accountsAre(account(CURRENT, 'JPY'))
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
})

describe('the currency of an account', () => {
  it('is the one the account itself holds', async () => {
    const { result } = renderCurrency(CURRENT)

    await waitFor(() => expect(result.current).toBe('JPY'))
  })

  it('falls back to the household while the account list is on its way', async () => {
    vi.mocked(api.accountsListAccounts).mockReturnValue(new Promise(() => {}) as never)
    vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
      data: { id: 'h', name: 'Home', currency_code: 'GBP' },
    } as never)
    const { result } = renderCurrency(CURRENT)

    await waitFor(() => expect(result.current).toBe('GBP'))
  })

  it('is the household currency when no account is chosen yet', async () => {
    const { result } = renderCurrency(null)

    await waitFor(() => expect(vi.mocked(api.accountsListAccounts)).toHaveBeenCalled())
    expect(result.current).toBe('EUR')
  })

  it('is the household currency for an account not in the list', async () => {
    const { result } = renderCurrency('22222222-2222-2222-2222-222222222222')

    await waitFor(() => expect(vi.mocked(api.accountsListAccounts)).toHaveBeenCalled())
    expect(result.current).toBe('EUR')
  })
})
