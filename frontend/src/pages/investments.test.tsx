import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { InstrumentKind, type PortfolioPublic, type PositionPublic } from '@/api'
import { Component as InvestmentsPage } from '@/pages/investments'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    investmentsGetPortfolio: vi.fn(),
    investmentsListTrades: vi.fn(),
    investmentsListInstruments: vi.fn(),
    investmentsListFxRates: vi.fn(),
    investmentsRefreshPrices: vi.fn(),
    investmentsDeleteInstrument: vi.fn(),
    investmentsDeleteTrade: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR' } }),
}))

const api = await import('@/api')

function position(overrides: Partial<PositionPublic> = {}): PositionPublic {
  return {
    instrument_id: 'i1',
    symbol: 'VWCE.DE',
    name: 'Vanguard FTSE All-World',
    kind: InstrumentKind.ETF,
    currency_code: 'EUR',
    quantity_micro: 10_000_000,
    is_open: true,
    last_price_micro: 12_845_000_000,
    fx_rate_micro: 1_000_000,
    cost_basis_minor: 100_000,
    market_value_minor: 128_450,
    unrealised_gain_minor: 28_450,
    realised_gain_minor: 0,
    ...overrides,
  }
}

function renderPage(positions: PositionPublic[], totals: Partial<PortfolioPublic> = {}) {
  vi.mocked(api.investmentsGetPortfolio).mockResolvedValue({
    data: {
      currency_code: 'EUR',
      data: positions,
      count: positions.length,
      total_cost_basis_minor: 0,
      total_market_value_minor: 0,
      total_unrealised_gain_minor: 0,
      total_realised_gain_minor: 0,
      unpriced_count: 0,
      ...totals,
    },
  } as never)
  vi.mocked(api.investmentsListTrades).mockResolvedValue({ data: { data: [], count: 0 } } as never)
  vi.mocked(api.investmentsListInstruments).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  vi.mocked(api.investmentsListFxRates).mockResolvedValue({
    data: { quote_code: 'EUR', data: [], count: 0, missing: [] },
  } as never)

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <InvestmentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The columns of the positions table, so a test can name the cell it means. */
const COLUMN = { price: 2, cost: 3, value: 4, unrealised: 5, realised: 6 } as const

async function cellsFor(symbol: string) {
  const label = await screen.findByText(symbol)
  const row = label.closest('tr')
  if (!row) throw new Error(`no row for ${symbol}`)
  const cells = within(row).getAllByRole('cell')
  return {
    row: within(row),
    text: (column: keyof typeof COLUMN) => cells[COLUMN[column]]?.textContent?.trim(),
  }
}

describe('the positions table', () => {
  it('shows a dash rather than a zero when a holding has no price', async () => {
    // Arrange: A holding the provider could not price
    renderPage([
      position({
        symbol: 'NVDA.US',
        last_price_micro: null,
        market_value_minor: null,
        unrealised_gain_minor: null,
      }),
    ])

    // Act: Read the row
    const { text } = await cellsFor('NVDA.US')

    // Assert: "Not known" and "worth nothing" must not look the same
    await waitFor(() => expect(text('value')).toBe('—'))
    expect(text('unrealised')).toBe('—')
    expect(text('price')).toBe('—')
  })

  it('shows a dash for unrealised on a sold position, not a zero', async () => {
    // Arrange: A position sold in full, which banked a loss
    renderPage([
      position({
        symbol: 'SGLN.L',
        is_open: false,
        quantity_micro: 0,
        cost_basis_minor: 0,
        market_value_minor: 0,
        unrealised_gain_minor: 0,
        realised_gain_minor: -14_764,
      }),
    ])

    // Act: Read the row
    const { row, text } = await cellsFor('SGLN.L')

    // Assert: It holds nothing, so there is nothing left to gain or lose on
    // paper, but the money it did make is still shown
    expect(row.getByText('Sold')).toBeInTheDocument()
    await waitFor(() => expect(text('unrealised')).toBe('—'))
    expect(text('realised')).toMatch(/147\.64/)
  })

  it('shows the realised gain of an open position that was trimmed', async () => {
    // Arrange: Still held, but part of it was sold earlier
    renderPage([position({ symbol: 'VWRL.L', realised_gain_minor: 9_449 })])

    // Act: Read the row
    const { text } = await cellsFor('VWRL.L')

    // Assert: Money banked by a partial sale must not be invisible
    await waitFor(() => expect(text('realised')).toMatch(/94\.49/))
  })

  it('shows a dash for a cost basis that has no exchange rate behind it', async () => {
    // Arrange: A dollar holding in a euro household, with no rate stored
    renderPage([
      position({
        symbol: 'VOO.US',
        currency_code: 'USD',
        fx_rate_micro: null,
        cost_basis_minor: null,
        market_value_minor: null,
        unrealised_gain_minor: null,
        realised_gain_minor: null,
      }),
    ])

    // Act: Read the row
    const { text } = await cellsFor('VOO.US')

    // Assert: A cost basis reported as zero would understate by the whole of
    // it, so every converted figure must be absent rather than a zero amount
    await waitFor(() => expect(text('cost')).toBe('—'))
    expect(text('value')).toBe('—')
    expect(text('unrealised')).toBe('—')
    expect(text('realised')).toBe('—')
  })

  it('shows a realised gain of exactly zero as an amount, not as a dash', async () => {
    // Arrange: A holding that has never been sold
    renderPage([position({ realised_gain_minor: 0 })])

    // Act: Read the row
    const { text } = await cellsFor('VWCE.DE')

    // Assert: Nothing banked is a known figure; unknown is what a dash means
    await waitFor(() => expect(text('realised')).toMatch(/0\.00/))
  })

  it('says how many holdings are missing from the total, in the plural', async () => {
    // Arrange: Two holdings that could not be valued
    renderPage([position()], { unpriced_count: 2 })

    // Act & Assert: Verify it reads as English rather than as a template
    expect(await screen.findByText(/2 of your holdings have/)).toBeInTheDocument()
  })

  it('uses the singular for exactly one', async () => {
    // Arrange: One holding that could not be valued
    renderPage([position()], { unpriced_count: 1 })

    // Act & Assert: Verify the wording changes with the count
    expect(await screen.findByText(/One of your holdings has/)).toBeInTheDocument()
  })
})
