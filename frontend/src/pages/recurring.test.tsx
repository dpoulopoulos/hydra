import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'

import { TransactionKind, type RecurringRulePublic, type UpcomingOccurrence } from '@/api'
import { formatMonth } from '@/lib/month'
import { formatMoney, formatSignedMoney } from '@/lib/money'
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

function renderPage(occurrences: UpcomingOccurrence[], netMinor = 0) {
  const rules = occurrences.map((occurrence, index) =>
    aRule({ id: `r${index}`, name: occurrence.name, kind: occurrence.kind }),
  )
  return renderWith(rules, occurrences, netMinor)
}

/** Render the page for a set of rules, with nothing projected for them. */
function renderRules(rules: RecurringRulePublic[]) {
  return renderWith(rules, [])
}

function renderWith(rules: RecurringRulePublic[], occurrences: UpcomingOccurrence[], netMinor = 0) {
  vi.mocked(api.recurringRulesListRecurringRules).mockResolvedValue({
    data: { data: rules, count: rules.length },
  } as never)
  vi.mocked(api.recurringRulesListUpcomingOccurrences).mockResolvedValue({
    data: { data: occurrences, count: occurrences.length, net_minor: netMinor },
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

/** The heading row of one month group, which carries that month's net. */
async function monthHeading(month: string) {
  const label = await screen.findByText(formatMonth(month))
  return label.parentElement as HTMLElement
}

/** The table row of a rule, by its name. */
async function ruleRow(name: string) {
  const cell = await screen.findByText(name)
  return cell.closest('tr') as HTMLElement
}

describe('a rule an archived account has stalled', () => {
  // The pass leaves such a rule where it stands, so the only visible symptom
  // is a next occurrence sitting in the past, which reads as a rendering
  // fault rather than as an explanation.
  it('says why its next date has stopped moving', async () => {
    renderRules([aRule({ name: 'Rent', is_blocked: true, next_occurrence_on: '2026-07-01' })])

    expect(await ruleRow('Rent')).toHaveTextContent('Account archived')
  })

  it('says nothing on a rule whose account is still open', async () => {
    renderRules([aRule({ name: 'Rent', is_blocked: false })])

    expect(await ruleRow('Rent')).not.toHaveTextContent('Account archived')
  })

  // The badge says the archived account is what stopped the rule recording,
  // and on a rule the household paused itself that is simply not true: it
  // would still be stopped with the account restored.
  it('says nothing on a rule the household paused itself', async () => {
    renderRules([aRule({ name: 'Rent', is_blocked: true, is_active: false })])

    const row = await ruleRow('Rent')
    expect(row).toHaveTextContent('Paused')
    expect(row).not.toHaveTextContent('Account archived')
  })

  // Nor on one that has run out of dates: there is nothing left for a
  // restored account to pick up.
  it('says nothing on a rule that has finished', async () => {
    renderRules([aRule({ name: 'Rent', is_blocked: true, next_occurrence_on: null })])

    const row = await ruleRow('Rent')
    expect(row).toHaveTextContent('Finished')
    expect(row).not.toHaveTextContent('Account archived')
  })
})

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

/**
 * Rent, a salary and a standing transfer to savings.
 *
 * The window's gross is meaningless: it counts the salary as an outgoing and
 * counts a move between the household's own accounts at all.
 */
const OCCURRENCES = [
  anOccurrence({ name: 'Rent', kind: TransactionKind.EXPENSE, occurs_on: '2026-04-01' }),
  anOccurrence({
    name: 'Salary',
    kind: TransactionKind.INCOME,
    amount_minor: 300_000,
    occurs_on: '2026-04-25',
  }),
  anOccurrence({
    name: 'To savings',
    kind: TransactionKind.TRANSFER,
    amount_minor: 50_000,
    occurs_on: '2026-04-28',
  }),
  anOccurrence({ name: 'Rent', kind: TransactionKind.EXPENSE, occurs_on: '2026-05-01' }),
]

describe('the total the "Still to come" card heads the window with', () => {
  it('is the net the window leaves, signed', async () => {
    renderPage(OCCURRENCES, 60_000)

    expect(await screen.findByText(formatSignedMoney(60_000, 'EUR'))).toBeInTheDocument()
  })

  it('is never the gross of the window, which counts income as an outgoing', async () => {
    renderPage(OCCURRENCES, 60_000)

    await screen.findByText(formatSignedMoney(60_000, 'EUR'))
    expect(screen.queryByText(formatMoney(590_000, 'EUR'))).not.toBeInTheDocument()
    expect(screen.queryByText(formatSignedMoney(590_000, 'EUR'))).not.toBeInTheDocument()
  })

  it('nets each month the same way, transfers left out', async () => {
    renderPage(OCCURRENCES, 60_000)

    // Every occurrence carries its own signed amount too, so a month's figure
    // is read from its heading rather than from the page as a whole.
    expect(await monthHeading('2026-04')).toHaveTextContent(formatSignedMoney(180_000, 'EUR'))
    expect(await monthHeading('2026-05')).toHaveTextContent(formatSignedMoney(-120_000, 'EUR'))
  })
})
