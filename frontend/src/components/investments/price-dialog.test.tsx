import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { type InstrumentPublic } from '@/api'
import { PriceDialog } from '@/components/investments/price-dialog'
import { pinNumberLocale } from '@/test/locale'

// Only the endpoint the dialog saves through is stood in for. What matters
// here is the `price_micro` a typed figure reaches the API as.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, investmentsSetInstrumentPrice: vi.fn() }
})

const api = await import('@/api')

// A reader who groups with a dot and writes the decimal point as a comma.
// Both halves matter: the field is filled in one direction and read in the
// other, and the two used to disagree about what a dot means.
pinNumberLocale('de-DE')

const instrument = {
  id: 'instrument-1',
  symbol: 'VWCE',
  currency_code: 'EUR',
  // €1.005, whose fraction is exactly a group's worth of digits.
  last_price_micro: 100_500_000,
  last_price_is_manual: true,
} as InstrumentPublic

function renderDialog() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <PriceDialog open instrument={instrument} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The `price_micro` the last save sent. */
function sentPrice() {
  const call = vi.mocked(api.investmentsSetInstrumentPrice).mock.calls.at(-1)?.[0] as
    { body: { price_micro: number } } | undefined
  return call?.body.price_micro
}

async function save(value?: string) {
  const user = userEvent.setup()
  renderDialog()

  const field = await screen.findByLabelText('Price per unit')
  if (value !== undefined) {
    await user.clear(field)
    await user.type(field, value)
  }
  await user.click(screen.getByRole('button', { name: 'Save price' }))
  await vi.waitFor(() => expect(api.investmentsSetInstrumentPrice).toHaveBeenCalled())
}

beforeEach(() => {
  vi.mocked(api.investmentsSetInstrumentPrice).mockResolvedValue({ data: {} } as never)
})

describe('the price field', () => {
  it('is filled with the separator the reader reads back as a decimal point', async () => {
    renderDialog()

    await vi.waitFor(() => expect(screen.getByLabelText('Price per unit')).toHaveValue('1,005'))
  })

  it('keeps the figure when a priced instrument is opened and saved again', async () => {
    await save()

    expect(sentPrice()).toBe(100_500_000)
  })

  it('reads a thousands separator as one rather than as a decimal point', async () => {
    // €1.200 typed the way this reader is shown the figure. It used to save as
    // €1.20, a share recorded at a thousandth of what it cost. #139.
    await save('1.200')

    expect(sentPrice()).toBe(120_000_000_000)
  })

  // The field is seeded from an effect, after the first render: whatever that
  // does to the form has to leave the field able to take a new number.
  it('saves the number typed over the one it opened on', async () => {
    const user = userEvent.setup()
    renderDialog()

    const price = await screen.findByLabelText('Price per unit')
    await vi.waitFor(() => expect(price).toHaveValue('1,005'))
    await user.clear(price)
    await user.type(price, '131,25')
    await user.click(screen.getByRole('button', { name: 'Save price' }))

    await vi.waitFor(() => expect(api.investmentsSetInstrumentPrice).toHaveBeenCalled())
    expect(sentPrice()).toBe(13_125_000_000)
  })

  it('reads this locale’s decimal point', async () => {
    await save('1200,4567')

    expect(sentPrice()).toBe(120_045_670_000)
  })

  it('says so when what was typed is not a number', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.clear(await screen.findByLabelText('Price per unit'))
    await user.type(screen.getByLabelText('Price per unit'), '1,2,3')
    await user.click(screen.getByRole('button', { name: 'Save price' }))

    expect(await screen.findByText('Enter a number.')).toBeInTheDocument()
    expect(api.investmentsSetInstrumentPrice).not.toHaveBeenCalled()
  })
})
