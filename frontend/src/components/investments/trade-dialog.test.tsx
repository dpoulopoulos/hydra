import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { InstrumentKind } from '@/api'
import { TradeDialog } from '@/components/investments/trade-dialog'

// The dialog reads its pickers and records the trade through the generated
// client, so the tests stand in for those endpoints and read back the body.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    investmentsListInstruments: vi.fn(),
    investmentsCreateTrade: vi.fn(),
    accountsListAccounts: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const api = await import('@/api')

const VWCE = '11111111-1111-1111-1111-111111111111'
const BROKER = '22222222-2222-2222-2222-222222222222'

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <TradeDialog open instrumentId={VWCE} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The body the last create call sent. */
function recordedBody() {
  const call = vi.mocked(api.investmentsCreateTrade).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

beforeEach(() => {
  vi.mocked(api.investmentsListInstruments).mockResolvedValue({
    data: {
      data: [
        {
          id: VWCE,
          household_id: 'h',
          symbol: 'VWCE.DE',
          name: 'Vanguard FTSE All-World',
          kind: InstrumentKind.ETF,
          currency_code: 'EUR',
          exchange: 'XETRA',
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: {
      data: [
        {
          id: BROKER,
          household_id: 'h',
          name: 'Broker',
          type: 'brokerage',
          currency_code: 'EUR',
          opening_balance_minor: 0,
          opening_balance_date: '2026-01-01',
          current_balance_minor: 500000,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.investmentsCreateTrade).mockResolvedValue({ data: {} } as never)
})

describe('recording a trade', () => {
  it('sends the units, price and fee that were typed', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Units'), '12')
    await user.type(screen.getByLabelText('Price per unit'), '118.50')
    await user.clear(screen.getByLabelText('Fees'))
    await user.type(screen.getByLabelText('Fees'), '1.50')
    await user.click(screen.getByRole('button', { name: 'Record trade' }))

    await waitFor(() => expect(api.investmentsCreateTrade).toHaveBeenCalled())
    expect(recordedBody()).toMatchObject({
      instrument_id: VWCE,
      side: 'buy',
      quantity_micro: 12_000_000,
      price_micro: 11_850_000_000,
      fee_minor: 150,
      brokerage_account_id: null,
      cash_amount_minor: null,
    })
  })

  it('sends the cash side only once a brokerage account is named', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Units'), '12')
    await user.type(screen.getByLabelText('Price per unit'), '118.50')

    // Until then the field is not even open for typing: there is no account
    // for the money to come out of.
    expect(screen.getByLabelText('Cash moved')).toBeDisabled()

    await user.click(screen.getByRole('combobox', { name: 'Bought through' }))
    await user.click(await screen.findByRole('option', { name: 'Broker' }))
    await user.type(screen.getByLabelText('Cash moved'), '1423.50')
    await user.click(screen.getByRole('button', { name: 'Record trade' }))

    await waitFor(() => expect(api.investmentsCreateTrade).toHaveBeenCalled())
    expect(recordedBody()).toMatchObject({
      brokerage_account_id: BROKER,
      cash_amount_minor: 142350,
    })
  })

  it('records a sale when the direction is switched', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('combobox', { name: 'Direction' }))
    await user.click(await screen.findByRole('option', { name: 'Sold' }))
    await user.type(screen.getByLabelText('Units'), '5')
    await user.type(screen.getByLabelText('Price per unit'), '120')
    await user.click(screen.getByRole('button', { name: 'Record trade' }))

    await waitFor(() => expect(api.investmentsCreateTrade).toHaveBeenCalled())
    expect(recordedBody()).toMatchObject({ side: 'sell', quantity_micro: 5_000_000 })
  })
})
