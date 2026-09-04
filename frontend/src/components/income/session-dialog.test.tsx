import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { IncomeSessionStatus, PaymentStatus, type IncomeSessionPublic } from '@/api'
import { SessionDialog } from '@/components/income/session-dialog'
import { pinNumberLocale } from '@/test/locale'

// The dialog reads its clients and the household currency through the
// generated client, so the tests stand in for those endpoints. What matters
// here is the `fee_minor` a saved session goes back to the API as.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    incomeListClients: vi.fn(),
    incomeUpdateSession: vi.fn(),
    incomeCreateSession: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

// The client picker shows a decrypted name, which needs the auth and vault
// providers the whole app sits under. None of that is what these tests are
// about, so the name renders as itself here.
vi.mock('@/components/income/client-name', () => ({
  ClientName: () => 'A client',
}))

const api = await import('@/api')

const CLIENT = '22222222-2222-2222-2222-222222222222'

// A three-decimal currency read in a locale that groups with a dot. Both
// halves matter: 1005 fils is "1.005" written with a bare `String`, which is
// a thousand and five to a de-DE reader rather than one and five thousandths.
pinNumberLocale('de-DE')

const session: IncomeSessionPublic = {
  id: 'session-1',
  client_id: CLIENT,
  occurs_on: '2026-03-04',
  fee_minor: 1005,
  status: IncomeSessionStatus.ATTENDED,
  payment_status: PaymentStatus.PAID,
  paid_on: '2026-03-04',
} as IncomeSessionPublic

function renderDialog(existing: IncomeSessionPublic | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <SessionDialog open session={existing} clientId={CLIENT} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The `fee_minor` the last save sent. */
function sentFee(call: { body: { fee_minor: number } } | undefined) {
  return call?.body.fee_minor
}

beforeEach(() => {
  vi.mocked(api.incomeListClients).mockResolvedValue({
    data: {
      data: [
        {
          id: CLIENT,
          name_ct: 'ct',
          default_rate_minor: 1005,
          default_account_id: 'a',
          archived_at: null,
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'BHD' },
  } as never)
  vi.mocked(api.incomeUpdateSession).mockResolvedValue({ data: {} } as never)
  vi.mocked(api.incomeCreateSession).mockResolvedValue({ data: {} } as never)
})

describe('the fee a saved session is filled with', () => {
  it('writes the separator the reader reads back as a decimal point', async () => {
    renderDialog(session)

    // The currency arrives with the household, so the field is refilled once
    // it lands rather than only on the first render.
    await vi.waitFor(() => expect(screen.getByLabelText('Fee')).toHaveValue('1,005'))
  })

  it('keeps the figure when a saved session is opened and saved again', async () => {
    const user = userEvent.setup()
    renderDialog(session)

    // Saving it untouched has to send back exactly what was read out.
    await screen.findByDisplayValue('1,005')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await vi.waitFor(() => expect(api.incomeUpdateSession).toHaveBeenCalled())
    expect(sentFee(vi.mocked(api.incomeUpdateSession).mock.calls.at(-1)?.[0] as never)).toBe(1005)
  })

  it("prefills a new session from the client's rate the same way", async () => {
    const user = userEvent.setup()
    renderDialog(null)

    await screen.findByDisplayValue('1,005')
    await user.click(screen.getByRole('button', { name: 'Log session' }))

    await vi.waitFor(() => expect(api.incomeCreateSession).toHaveBeenCalled())
    expect(sentFee(vi.mocked(api.incomeCreateSession).mock.calls.at(-1)?.[0] as never)).toBe(1005)
  })
})
