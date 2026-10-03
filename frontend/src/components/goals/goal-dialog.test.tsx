import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GoalPublic } from '@/api'
import { GoalDialog } from '@/components/goals/goal-dialog'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    accountsListAccounts: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
    goalsCreateGoal: vi.fn(),
    goalsUpdateGoal: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const api = await import('@/api')

const CURRENT = 'current'
const SAVINGS = 'savings'

function account(id: string, name: string, type: string) {
  return {
    id,
    name,
    type,
    household_id: 'h',
    currency_code: 'EUR',
    opening_balance_minor: 0,
    opening_balance_date: '2026-01-01',
    current_balance_minor: 0,
    created_at: '2026-01-01T00:00:00Z',
    archived_at: null,
  }
}

function renderDialog(goal: GoalPublic | null = null) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      <GoalDialog open goal={goal} onOpenChange={() => {}} />
    </QueryClientProvider>,
  )
}

/** The body of the last create request. */
function createdBody() {
  const call = vi.mocked(api.goalsCreateGoal).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

beforeEach(() => {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: {
      data: [account(CURRENT, 'Everyday', 'current'), account(SAVINGS, 'Rainy day', 'savings')],
      count: 2,
    },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.goalsCreateGoal).mockResolvedValue({ data: {} } as never)
  vi.mocked(api.goalsUpdateGoal).mockResolvedValue({ data: {} } as never)
})

describe('adding a goal', () => {
  it('offers only savings accounts', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.click(await screen.findByRole('combobox', { name: 'Savings account' }))

    expect(await screen.findByRole('option', { name: 'Rainy day' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Everyday' })).not.toBeInTheDocument()
  })

  it('sends the price in minor units and the date', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'New car')
    await user.click(screen.getByRole('combobox', { name: 'Savings account' }))
    await user.click(await screen.findByRole('option', { name: 'Rainy day' }))
    await user.type(screen.getByLabelText('Price'), '20000')
    await user.type(screen.getByLabelText('Reach it by'), '2027-12-31')
    await user.click(screen.getByRole('button', { name: 'Add goal' }))

    await waitFor(() => expect(api.goalsCreateGoal).toHaveBeenCalled())
    expect(createdBody()).toEqual({
      name: 'New car',
      account_id: SAVINGS,
      target_minor: 2_000_000,
      target_date: '2027-12-31',
    })
  })

  it('leaves the date out when none is given', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Holiday')
    await user.click(screen.getByRole('combobox', { name: 'Savings account' }))
    await user.click(await screen.findByRole('option', { name: 'Rainy day' }))
    await user.type(screen.getByLabelText('Price'), '1500')
    await user.click(screen.getByRole('button', { name: 'Add goal' }))

    await waitFor(() => expect(api.goalsCreateGoal).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({ target_date: null })
  })

  it('asks for an account before saving', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Holiday')
    await user.type(screen.getByLabelText('Price'), '1500')
    await user.click(screen.getByRole('button', { name: 'Add goal' }))

    expect(
      await screen.findByText('Pick the savings account the money goes into.'),
    ).toBeInTheDocument()
    expect(api.goalsCreateGoal).not.toHaveBeenCalled()
  })
})
