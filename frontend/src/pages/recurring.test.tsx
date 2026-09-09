import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { TransactionKind, type RecurringRulePublic, type UpcomingOccurrence } from '@/api'
import { Component as RecurringPage } from '@/pages/recurring'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    recurringRulesListRecurringRules: vi.fn(),
    recurringRulesListUpcomingOccurrences: vi.fn(),
    recurringRulesRunRecurringRules: vi.fn(),
    recurringRulesUpdateRecurringRule: vi.fn(),
    recurringRulesDeleteRecurringRule: vi.fn(),
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/hooks/use-household', () => ({
  useCurrency: () => 'EUR',
  useHousehold: () => ({ data: { currency_code: 'EUR' } }),
  useIsHouseholdOwner: () => true,
}))

const api = await import('@/api')

const ACCOUNT_ID = 'a1'

function aRule(overrides: Partial<RecurringRulePublic> = {}): RecurringRulePublic {
  return {
    id: 'r1',
    household_id: 'h1',
    account_id: ACCOUNT_ID,
    name: 'Rent',
    kind: TransactionKind.EXPENSE,
    amount_minor: 120_000,
    start_date: '2026-01-01',
    next_occurrence_on: '2026-09-01',
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

function anOccurrence(overrides: Partial<UpcomingOccurrence> = {}): UpcomingOccurrence {
  return {
    rule_id: 'r1',
    name: 'Rent',
    kind: TransactionKind.EXPENSE,
    amount_minor: 120_000,
    occurs_on: '2026-09-01',
    account_id: ACCOUNT_ID,
    ...overrides,
  }
}

function renderPage(occurrences: UpcomingOccurrence[]) {
  const rules = occurrences.map((occurrence, index) =>
    aRule({ id: `r${index}`, name: occurrence.name, kind: occurrence.kind }),
  )
  vi.mocked(api.recurringRulesListRecurringRules).mockResolvedValue({
    data: { data: rules, count: rules.length },
  } as never)
  vi.mocked(api.recurringRulesListUpcomingOccurrences).mockResolvedValue({
    data: { data: occurrences, count: occurrences.length, total_minor: 0 },
  } as never)
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: { data: [{ id: ACCOUNT_ID, name: 'Current' }], count: 1 },
  } as never)

  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <RecurringPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The "Still to come" row for a rule, once the projection has landed. */
async function upcomingRow(name: string) {
  const card = (await screen.findByText('Still to come')).closest('[data-slot="card"]')
  expect(card).not.toBeNull()
  const row = await within(card as HTMLElement).findByText(name)
  return row.closest('li') as HTMLElement
}

describe('the "Still to come" card', () => {
  it('draws money out with a minus', async () => {
    renderPage([anOccurrence({ name: 'Rent', kind: TransactionKind.EXPENSE })])

    expect(await upcomingRow('Rent')).toHaveTextContent('-€1,200.00')
  })

  it('draws money in with a plus', async () => {
    renderPage([
      anOccurrence({ name: 'Salary', kind: TransactionKind.INCOME, amount_minor: 300_000 }),
    ])

    expect(await upcomingRow('Salary')).toHaveTextContent('+€3,000.00')
  })

  // A transfer moves money between the household's own accounts, so it is
  // neither spending nor income. The month's net leaves it out; a minus in
  // the row would read as spending and disagree with the total above it.
  it('draws a transfer plain, with no sign at all', async () => {
    renderPage([
      anOccurrence({ name: 'To savings', kind: TransactionKind.TRANSFER, amount_minor: 50_000 }),
    ])

    const row = await upcomingRow('To savings')
    expect(row).toHaveTextContent('€500.00')
    expect(row).not.toHaveTextContent('-€500.00')
    expect(row).not.toHaveTextContent('+€500.00')
  })
})
