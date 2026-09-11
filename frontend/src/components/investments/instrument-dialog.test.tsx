import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InstrumentDialog } from '@/components/investments/instrument-dialog'

// The search is one of twenty API calls the provider allows in a day, so what
// these tests are really about is how many of them a piece of typing costs.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    investmentsSearchSymbols: vi.fn(),
    investmentsCreateInstrument: vi.fn(),
    investmentsUpdateInstrument: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const api = await import('@/api')

/** The dialog behind a button that closes and reopens it, as a page does. */
function Harness() {
  const [open, setOpen] = useState(true)
  return (
    <>
      <button onClick={() => setOpen(true)}>Reopen</button>
      <InstrumentDialog open={open} instrument={null} onOpenChange={setOpen} />
    </>
  )
}

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
}

/**
 * The match the provider answered with, once it has been asked.
 *
 * The search waits 400ms for the typing to stop before it goes anywhere, which
 * is most of the time a find is willing to wait by default.
 */
function findMatch() {
  return screen.findByRole('button', { name: /Vanguard FTSE All-World/ }, { timeout: 3000 })
}

function searchBox() {
  return screen.getByPlaceholderText('Search by name, e.g. All-World')
}

/** How many times the provider has been asked, and what for. */
function searchesFor() {
  return vi
    .mocked(api.investmentsSearchSymbols)
    .mock.calls.map((call) => (call[0] as { query: { q: string } }).query.q)
}

beforeEach(() => {
  vi.mocked(api.investmentsSearchSymbols).mockResolvedValue({
    data: {
      data: [{ symbol: 'VWCE.DE', name: 'Vanguard FTSE All-World', exchange: 'XETRA' }],
      count: 1,
    },
  } as never)
})

describe('searching for a symbol', () => {
  it('asks the provider once for a word typed in one go', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(searchBox(), 'vwce')
    expect(await findMatch()).toBeInTheDocument()
    expect(searchesFor()).toEqual(['vwce'])
  })

  it('drops the matches as soon as the box is cleared', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(searchBox(), 'vwce')
    expect(await findMatch()).toBeInTheDocument()

    await user.clear(searchBox())

    expect(
      screen.queryByRole('button', { name: /Vanguard FTSE All-World/ }),
    ).not.toBeInTheDocument()
  })

  it('fills the form in from the match that was picked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(searchBox(), 'vwce')
    await user.click(await findMatch())

    expect(screen.getByLabelText('Symbol')).toHaveValue('VWCE.DE')
    expect(screen.getByLabelText('Name')).toHaveValue('Vanguard FTSE All-World')
    expect(searchBox()).toHaveValue('')
  })

  it('starts with an empty box when the dialog is reopened', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(searchBox(), 'vwce')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Reopen' }))

    expect(searchBox()).toHaveValue('')
    expect(
      screen.queryByRole('button', { name: /Vanguard FTSE All-World/ }),
    ).not.toBeInTheDocument()
  })
})
