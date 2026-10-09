import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AccountPublic, BankConnectionPublic } from '@/api'
import { Component as BankPage } from '@/pages/settings/bank'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    bankGetBankStatus: vi.fn(),
    bankListAspsps: vi.fn(),
    bankListBankConnections: vi.fn(),
    bankStartBankConnection: vi.fn(),
    bankSyncBankConnection: vi.fn(),
    bankDisconnectBank: vi.fn(),
    bankUpdateBankAccount: vi.fn(),
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

let isOwner = false

vi.mock('@/hooks/use-household', () => ({
  useIsHouseholdOwner: () => isOwner,
  useCurrency: () => 'EUR',
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 'u1', is_superuser: false } }),
}))

const api = await import('@/api')
const { toast } = await import('sonner')

function account(overrides: Partial<AccountPublic>): AccountPublic {
  return {
    id: 'a1',
    household_id: 'h1',
    name: 'Current',
    type: 'checking',
    currency_code: 'EUR',
    opening_balance_minor: 0,
    opening_balance_date: '2026-01-01',
    ...overrides,
  } as AccountPublic
}

function connection(overrides: Partial<BankConnectionPublic> = {}): BankConnectionPublic {
  return {
    id: 'c1',
    aspsp_name: 'Mock ASPSP',
    aspsp_country: 'GR',
    status: 'active',
    valid_until: '2027-04-01T00:00:00Z',
    last_synced_at: null,
    last_sync_error: null,
    created_by_user_id: 'u1',
    created_at: '2026-10-01T00:00:00Z',
    accounts: [
      {
        id: 'b1',
        connection_id: 'c1',
        name: 'Everyday account',
        iban: 'GR1601101250000000012300695',
        currency_code: 'EUR',
        account_id: null,
        import_from: null,
        sync_enabled: true,
        flip_direction: false,
      },
    ],
    ...overrides,
  } as BankConnectionPublic
}

function program({
  enabled = true,
  connections = [connection()],
}: { enabled?: boolean; connections?: BankConnectionPublic[] } = {}) {
  vi.mocked(api.bankGetBankStatus).mockResolvedValue({ data: { enabled } } as never)
  vi.mocked(api.bankListBankConnections).mockResolvedValue({
    data: { data: connections, count: connections.length },
  } as never)
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: {
      data: [
        account({ id: 'a1', name: 'Current' }),
        account({ id: 'a2', name: 'Dollars', currency_code: 'USD' }),
      ],
      count: 2,
    },
  } as never)
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BankPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  isOwner = false
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the bank settings', () => {
  it('says bank sync is off rather than offering a button that fails', async () => {
    program({ enabled: false })

    renderPage()

    expect(await screen.findByText('Bank sync is off')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Connect' })).not.toBeInTheDocument()
    expect(api.bankListBankConnections).not.toHaveBeenCalled()
  })

  it('sends the browser to the bank chosen', async () => {
    program({ connections: [] })
    vi.mocked(api.bankListAspsps).mockResolvedValue({
      data: { data: [{ name: 'Mock ASPSP', country: 'GR' }], count: 1 },
    } as never)
    vi.mocked(api.bankStartBankConnection).mockResolvedValue({
      data: { url: 'https://bank.example/login' },
    } as never)
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('combobox', { name: 'Country' }))
    await user.click(await screen.findByRole('option', { name: 'Greece' }))
    await user.click(await screen.findByRole('combobox', { name: 'Bank' }))
    await user.click(await screen.findByRole('option', { name: 'Mock ASPSP' }))
    await user.click(screen.getByRole('button', { name: 'Connect' }))

    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://bank.example/login'))
    expect(api.bankListAspsps).toHaveBeenCalledWith({ query: { country: 'GR' } })
    expect(api.bankStartBankConnection).toHaveBeenCalledWith({
      body: { aspsp_name: 'Mock ASPSP', aspsp_country: 'GR' },
    })
  })

  it('links a bank account only to an account in its own currency', async () => {
    program()
    vi.mocked(api.bankUpdateBankAccount).mockResolvedValue({ data: {} } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(
      await screen.findByRole('combobox', { name: 'Hydra account for Everyday account' }),
    )
    const listbox = await screen.findByRole('listbox')
    expect(within(listbox).queryByText('Dollars (USD)')).not.toBeInTheDocument()
    await user.click(within(listbox).getByRole('option', { name: 'Current (EUR)' }))

    await waitFor(() =>
      expect(api.bankUpdateBankAccount).toHaveBeenCalledWith({
        path: { bank_account_id: 'b1' },
        body: { account_id: 'a1' },
      }),
    )
    // Linking fetches nothing, so the page says what does.
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        'Linked. Click Sync now to bring in its transactions.',
      ),
    )
    // The account may have taken the bank's IBAN, so it is asked for again.
    await waitFor(() => expect(api.accountsListAccounts).toHaveBeenCalledTimes(2))
  })

  it('offers the sync switch only once a bank account is linked', async () => {
    // An unlinked account is never synced, so a switch saying it is would lie.
    program()

    renderPage()

    const toggle = await screen.findByRole('switch', { name: 'Sync Everyday account' })
    expect(toggle).toBeDisabled()
    expect(toggle).not.toBeChecked()
  })

  it('flips money in and out for a bank account', async () => {
    program()
    vi.mocked(api.bankUpdateBankAccount).mockResolvedValue({ data: {} } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(
      await screen.findByRole('switch', { name: 'Flip money in and out for Everyday account' }),
    )

    await waitFor(() =>
      expect(api.bankUpdateBankAccount).toHaveBeenCalledWith({
        path: { bank_account_id: 'b1' },
        body: { flip_direction: true },
      }),
    )
    // Not a link, so the page does not say it is one.
    expect(toast.success).not.toHaveBeenCalled()
  })

  it('says how many rows a sync brought in', async () => {
    program()
    vi.mocked(api.bankSyncBankConnection).mockResolvedValue({
      data: { status: 'succeeded', new_count: 3, fetched_count: 5 },
    } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Sync now' }))

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        '3 new transactions in your inbox',
        expect.anything(),
      ),
    )
  })

  it('reports a sync the bank refused', async () => {
    program()
    vi.mocked(api.bankSyncBankConnection).mockResolvedValue({
      data: { status: 'failed', new_count: 0, fetched_count: 0, error: 'The bank is down.' },
    } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Sync now' }))

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('The bank is down.'))
  })

  it('offers a new login for an expired connection instead of a sync', async () => {
    program({ connections: [connection({ status: 'expired' })] })

    renderPage()

    expect(await screen.findByRole('button', { name: 'Log in again' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sync now' })).not.toBeInTheDocument()
  })

  it('offers to disconnect only to whoever connected it or an owner', async () => {
    program({ connections: [connection({ created_by_user_id: 'someone-else' })] })

    renderPage()

    expect(await screen.findByText('Mock ASPSP')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Disconnect' })).not.toBeInTheDocument()
  })

  it('disconnects after asking', async () => {
    program()
    vi.mocked(api.bankDisconnectBank).mockResolvedValue({ data: { message: 'ok' } } as never)
    const user = userEvent.setup()

    renderPage()

    await user.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('alertdialog')
    await user.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    await waitFor(() =>
      expect(api.bankDisconnectBank).toHaveBeenCalledWith({ path: { connection_id: 'c1' } }),
    )
  })
})
