import { render } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'

import type { IncomeExpenseReport, MonthlyFlow } from '@/api'
import { IncomeExpenseChart, SavingsTrendChart } from '@/components/charts/income-expense-chart'
import { readFirstTooltip, sizeCharts } from '@/test/charts'

beforeAll(sizeCharts)

function month(overrides: Partial<MonthlyFlow>): MonthlyFlow {
  return {
    month: '2026-01',
    income_minor: 0,
    expense_minor: 0,
    net_minor: 0,
    cumulative_net_minor: 0,
    ...overrides,
  }
}

function report(months: MonthlyFlow[], currency: string): IncomeExpenseReport {
  return {
    period: { date_from: '2026-01-01', date_to: '2026-01-31', currency_code: currency },
    months,
    total_income_minor: 0,
    total_expense_minor: 0,
    total_net_minor: 0,
  }
}

// The API speaks minor units and the currency decides how many of them make a
// major one, so a chart that converts down for the mark and back up with a
// constant disagrees with itself for every currency that is not two-decimal.
describe('IncomeExpenseChart', () => {
  it('reads a bar in a two-decimal currency', () => {
    const months = [month({ income_minor: 500_000, expense_minor: 200_000 })]
    const { container } = render(
      <IncomeExpenseChart report={report(months, 'EUR')} currency="EUR" />,
    )

    expect(readFirstTooltip(container)).toContain('€5,000.00')
  })

  it('reads a bar in a zero-decimal currency', () => {
    const months = [month({ income_minor: 500_000, expense_minor: 200_000 })]
    const { container } = render(
      <IncomeExpenseChart report={report(months, 'JPY')} currency="JPY" />,
    )

    expect(readFirstTooltip(container)).toContain('¥500,000')
  })
})

describe('SavingsTrendChart', () => {
  it('reads a point in a zero-decimal currency', () => {
    const months = [month({ net_minor: 300_000, cumulative_net_minor: 600_000 })]
    const { container } = render(
      <SavingsTrendChart report={report(months, 'JPY')} currency="JPY" />,
    )

    expect(readFirstTooltip(container)).toContain('¥600,000')
  })
})
