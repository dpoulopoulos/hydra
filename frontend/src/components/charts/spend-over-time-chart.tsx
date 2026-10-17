import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from 'recharts'

import type { SpendOverTimeReport, TimeGranularity } from '@/api'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { useLocale } from '@/lib/locale-context'
import { formatCompactAmount, formatMoney } from '@/lib/money'
import { formatDate, formatMonth } from '@/lib/month'

/**
 * Spending over a period.
 *
 * One bar per bucket: each figure is a sum for a day or a month, which a bar
 * says and a line does not. Bars also survive one big day, such as the rent:
 * a line hugs zero for the rest of the month, while each small day still
 * stands as its own mark. The report fills empty buckets with zero, so a
 * quiet day shows as a gap in the row rather than as missing time.
 */
export function SpendOverTimeChart({
  report,
  currency,
}: {
  report: SpendOverTimeReport
  currency: string
}) {
  const locale = useLocale()
  const isMonthly = report.granularity === ('month' as TimeGranularity)

  const data = report.points.map((point) => ({
    bucket: point.bucket,
    label: isMonthly
      ? formatMonth(point.bucket.slice(0, 7), { month: 'short', year: '2-digit' })
      : formatDate(point.bucket, { day: 'numeric', month: 'short' }),
    amount: point.amount_minor,
  }))

  const config: ChartConfig = {
    amount: { label: 'Spent', color: 'var(--chart-1)' },
  }

  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <BarChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 4 }} barCategoryGap={2}>
        <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-border" />
        <XAxis
          dataKey="label"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          minTickGap={24}
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
          cursor={{ fill: 'var(--muted)', fillOpacity: 0.5 }}
          content={
            <ChartTooltipContent
              labelKey="label"
              formatter={(value) => formatMoney(Number(value), currency, locale)}
            />
          }
        />
        {/* 4px rounded tops, square against the baseline. */}
        <Bar dataKey="amount" fill="var(--chart-1)" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ChartContainer>
  )
}
