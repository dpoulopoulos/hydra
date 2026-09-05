import { render } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'

import { TimeGranularity, TransactionKind, type SpendOverTimeReport } from '@/api'
import { SpendOverTimeChart } from '@/components/charts/spend-over-time-chart'
import { readFirstTooltip, sizeCharts } from '@/test/charts'

beforeAll(sizeCharts)

function report(amountMinor: number, currency: string): SpendOverTimeReport {
  return {
    period: { date_from: '2026-01-01', date_to: '2026-01-31', currency_code: currency },
    granularity: TimeGranularity.DAY,
    kind: TransactionKind.EXPENSE,
    total_minor: amountMinor,
    average_minor: amountMinor,
    points: [{ bucket: '2026-01-02', amount_minor: amountMinor, transaction_count: 1 }],
  }
}

describe('SpendOverTimeChart', () => {
  it('reads a point in a two-decimal currency', () => {
    const { container } = render(
      <SpendOverTimeChart report={report(500_000, 'EUR')} currency="EUR" />,
    )

    expect(readFirstTooltip(container)).toContain('€5,000.00')
  })

  it('reads a point in a zero-decimal currency', () => {
    const { container } = render(
      <SpendOverTimeChart report={report(500_000, 'JPY')} currency="JPY" />,
    )

    expect(readFirstTooltip(container)).toContain('¥500,000')
  })
})
