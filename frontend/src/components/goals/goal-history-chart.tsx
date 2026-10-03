import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, XAxis, YAxis } from 'recharts'

import type { GoalHistory } from '@/api'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { useLocale } from '@/lib/locale-context'
import { formatCompactAmount, formatMoney } from '@/lib/money'
import { formatMonth } from '@/lib/month'

/**
 * What a goal saved each month.
 *
 * Bars rather than a line: each month is its own amount, and a month that took
 * money back out is a bar below zero, drawn in the negative colour. The pace a
 * dated goal needs is a dashed line across, so a month is read against it
 * without any arithmetic.
 */
export function GoalHistoryChart({
  history,
  currency,
  neededPerMonth,
}: {
  history: GoalHistory
  currency: string
  /** What each month has to add to reach the target in time, if the goal has a date. */
  neededPerMonth?: number | null
}) {
  const locale = useLocale()

  const data = history.months.map((month) => ({
    label: formatMonth(month.month, { month: 'short', year: '2-digit' }),
    saved: month.net_minor,
  }))

  const config: ChartConfig = {
    saved: { label: 'Saved', color: 'var(--chart-1)' },
  }

  return (
    <ChartContainer config={config} className="aspect-auto h-56 w-full">
      <BarChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 4 }}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          tick={{ fontSize: 12 }}
          className="fill-muted-foreground"
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={56}
          tick={{ fontSize: 12 }}
          className="fill-muted-foreground"
          tickFormatter={(value: number) => formatCompactAmount(value, currency, locale)}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelKey="label"
              formatter={(value) => formatMoney(Number(value), currency, locale)}
            />
          }
        />
        {neededPerMonth ? (
          <ReferenceLine
            y={neededPerMonth}
            strokeDasharray="4 4"
            className="stroke-muted-foreground"
            label={{
              value: 'Needed',
              position: 'insideTopRight',
              fontSize: 11,
              className: 'fill-muted-foreground',
            }}
          />
        ) : null}
        <Bar dataKey="saved" radius={[4, 4, 0, 0]} maxBarSize={28}>
          {data.map((entry) => (
            <Cell
              key={entry.label}
              fill={entry.saved < 0 ? 'var(--negative)' : 'var(--color-saved)'}
            />
          ))}
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}
