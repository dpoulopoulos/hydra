import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'

import type { SpendByCategoryReport } from '@/api'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { useLocale } from '@/lib/locale-context'
import { formatAmount, formatMoney } from '@/lib/money'
import { toColoredSlices } from '@/lib/chart-palette'

/**
 * Where a month's money went, by category.
 *
 * Horizontal bars: the job is comparing magnitudes across named things, and
 * horizontal bars leave room for real category names instead of rotated
 * labels. A single measure, so no legend; the title names it, and each bar
 * carries its own value.
 */
export function SpendByCategoryChart({
  report,
  currency,
}: {
  report: SpendByCategoryReport
  currency: string
}) {
  const locale = useLocale()
  const rows = toColoredSlices(
    report.slices.map((slice) => ({
      key: slice.category_id ?? slice.category_name,
      label: slice.category_name,
      amount: slice.amount_minor,
    })),
  )

  const data = rows.map((row) => ({ ...row, fill: row.color }))

  const config: ChartConfig = {
    amount: { label: 'Spent' },
  }

  return (
    <ChartContainer
      config={config}
      className="h-full w-full"
      style={{ height: rows.length * 40 + 24 }}
    >
      <BarChart data={data} layout="vertical" margin={{ left: 4, right: 56, top: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} strokeDasharray="3 3" className="stroke-border" />
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="label"
          width={130}
          tickLine={false}
          axisLine={false}
          tick={{ fontSize: 12 }}
          className="fill-muted-foreground"
        />
        <ChartTooltip
          cursor={false}
          content={
            <ChartTooltipContent
              formatter={(value) => formatMoney(Number(value), currency, locale)}
              labelKey="label"
            />
          }
        />
        {/* 4px rounded ends on the data side, square against the baseline. */}
        <Bar
          dataKey="amount"
          radius={[0, 4, 4, 0]}
          barSize={16}
          label={{
            position: 'right',
            offset: 8,
            fontSize: 12,
            formatter: (value: unknown) => formatAmount(Number(value), currency, locale),
            className: 'fill-muted-foreground',
          }}
        />
      </BarChart>
    </ChartContainer>
  )
}
