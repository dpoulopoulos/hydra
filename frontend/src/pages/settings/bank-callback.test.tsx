import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Component as BankCallback } from '@/pages/settings/bank-callback'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, bankCompleteBankConnection: vi.fn() }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const api = await import('@/api')

function renderCallback(search: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[`/settings/bank/callback${search}`]}>
          <Routes>
            <Route path="/settings/bank/callback" element={<BankCallback />} />
            <Route path="/settings/bank" element={<p>the bank settings</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

describe('coming back from the bank', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('trades the code for the connection once, and moves on to the settings', async () => {
    vi.mocked(api.bankCompleteBankConnection).mockResolvedValue({
      data: { aspsp_name: 'Mock ASPSP', accounts: [] },
    } as never)

    renderCallback('?code=the-code&state=the-state')

    expect(await screen.findByText('the bank settings')).toBeInTheDocument()
    expect(api.bankCompleteBankConnection).toHaveBeenCalledTimes(1)
    expect(api.bankCompleteBankConnection).toHaveBeenCalledWith({
      body: { code: 'the-code', state: 'the-state' },
    })
  })

  it('says why when the bank login was cancelled, without asking the API', async () => {
    renderCallback('?error=access_denied&error_description=You%20cancelled.&state=s')

    expect(await screen.findByText('You cancelled.')).toBeInTheDocument()
    expect(api.bankCompleteBankConnection).not.toHaveBeenCalled()
  })

  it('says why when the API refuses the code', async () => {
    vi.mocked(api.bankCompleteBankConnection).mockResolvedValue({
      error: { detail: 'This login has expired. Start again.' },
    } as never)

    renderCallback('?code=c&state=s')

    expect(await screen.findByText('This login has expired. Start again.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to banks' })).toHaveAttribute(
      'href',
      '/settings/bank',
    )
  })

  it('says the address is incomplete when the code is missing', async () => {
    renderCallback('?state=s')

    await waitFor(() => expect(screen.getByText(/missing what the bank sends back/)).toBeVisible())
    expect(api.bankCompleteBankConnection).not.toHaveBeenCalled()
  })
})
