import { Bar, BarChart, CartesianGrid, Line, LineChart, XAxis, YAxis } from 'recharts'

import type { IncomeExpenseReport } from '@/api'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { useLocale } from '@/lib/locale-context'
import { formatCompactAmount, formatMoney } from '@/lib/money'
import { formatMonth } from '@/lib/month'

/**
 * Money in against money out, month by month.
 *
 * Two series of the same measure, so grouped bars on one scale with a legend.
 * The running total is a different measure at a different magnitude, so it gets
 * its own chart below rather than a second y-axis: two scales in one frame
 * invite a comparison that is not real.
 */
export function IncomeExpenseChart({
  report,
  currency,
}: {
  report: IncomeExpenseReport
  currency: string
}) {
  const locale = useLocale()

  const data = report.months.map((month) => ({
    label: formatMonth(month.month, { month: 'short', year: '2-digit' }),
    income: month.income_minor,
    expense: month.expense_minor,
  }))

  const config: ChartConfig = {
    income: { label: 'Money in', color: 'var(--positive)' },
    expense: { label: 'Money out', color: 'var(--negative)' },
  }

  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
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
              formatter={(value) => formatMoney(Number(value), currency, locale)}
            />
          }
        />
        <ChartLegend content={<ChartLegendContent />} />
        {/* A 2px gap between the pair, so adjacent bars read as two marks. */}
        <Bar dataKey="income" fill="var(--color-income)" radius={[4, 4, 0, 0]} maxBarSize={28} />
        <Bar dataKey="expense" fill="var(--color-expense)" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ChartContainer>
  )
}

/**
 * The running total of what was kept.
 *
 * Its own chart rather than a line over the bars above: it is a cumulative
 * total, a different measure on a different scale, and putting it on a second
 * axis would let the eye compare two things that do not share units.
 */
export function SavingsTrendChart({
  report,
  currency,
}: {
  report: IncomeExpenseReport
  currency: string
}) {
  const locale = useLocale()

  const data = report.months.map((month) => ({
    label: formatMonth(month.month, { month: 'short', year: '2-digit' }),
    cumulative: month.cumulative_net_minor,
  }))

  const config: ChartConfig = {
    cumulative: { label: 'Saved, running total', color: 'var(--chart-1)' },
  }

  return (
    <ChartContainer config={config} className="aspect-auto h-56 w-full">
      <LineChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 4 }}>
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
        <Line
          dataKey="cumulative"
          type="monotone"
          stroke="var(--chart-1)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, className: 'stroke-background' }}
        />
      </LineChart>
    </ChartContainer>
  )
}
