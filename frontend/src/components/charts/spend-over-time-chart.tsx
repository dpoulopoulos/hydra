import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts'

import type { SpendOverTimeReport, TimeGranularity } from '@/api'
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { formatMoney, toMajor } from '@/lib/money'
import { formatDate, formatMonth } from '@/lib/month'

/**
 * Spending over a period.
 *
 * One measure over time, so an area with a 2px line: the shape of the trend is
 * the point, and the fill makes a run of quiet days legible. The report fills
 * empty buckets with zero, so the line never jumps a gap that would imply
 * missing time.
 */
export function SpendOverTimeChart({
  report,
  currency,
}: {
  report: SpendOverTimeReport
  currency: string
}) {
  const isMonthly = report.granularity === ('month' as TimeGranularity)

  const data = report.points.map((point) => ({
    bucket: point.bucket,
    label: isMonthly
      ? formatMonth(point.bucket.slice(0, 7), { month: 'short', year: '2-digit' })
      : formatDate(point.bucket, { day: 'numeric', month: 'short' }),
    amount: toMajor(point.amount_minor, currency),
  }))

  const config: ChartConfig = {
    amount: { label: 'Spent', color: 'var(--chart-1)' },
  }

  return (
    <ChartContainer config={config} className="aspect-auto h-64 w-full">
      <AreaChart data={data} margin={{ left: 4, right: 8, top: 8, bottom: 4 }}>
        <defs>
          <linearGradient id="spend-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.25} />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.02} />
          </linearGradient>
        </defs>
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
          tickFormatter={(value: number) =>
            new Intl.NumberFormat(undefined, { notation: 'compact' }).format(value)
          }
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelKey="label"
              formatter={(value) => formatMoney(Math.round(Number(value) * 100), currency)}
            />
          }
        />
        <Area
          dataKey="amount"
          type="monotone"
          stroke="var(--chart-1)"
          strokeWidth={2}
          fill="url(#spend-fill)"
          activeDot={{ r: 4, strokeWidth: 2, className: 'stroke-background' }}
        />
      </AreaChart>
    </ChartContainer>
  )
}
