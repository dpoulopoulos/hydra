import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, XAxis, YAxis } from 'recharts'

import { ForecastBasis, type IncomeForecast } from '@/api'
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart'
import { useLocale } from '@/lib/locale-context'
import { formatMoney, toMajor, toMinor } from '@/lib/money'
import { formatMonth } from '@/lib/month'

type Point = {
  label: string
  earned: number | null
  estimate: number | null
  band: [number, number] | null
  owed: number | null
}

/**
 * What the months earned, what is still owed, and where the next two land.
 *
 * A line rather than bars, because these are one quantity moving through time
 * rather than a set of separate totals to compare. A practice that is growing
 * or winding down says so in the slope, which is the thing a row of bars makes
 * you work out for yourself.
 *
 * The earned line stops at the last complete month and the estimate carries on
 * from where it stopped, dashed and inside a widening band. The join is the
 * point of it: the same measure, continuing, with the certainty draining out of
 * it. A cone that opens as it goes is what uncertainty compounding actually
 * looks like — next month is a guess about a month further off than this one.
 *
 * Debt is the balance still outstanding at the close of each month, not what
 * that month's own work was owed. It rises when an hour goes unpaid and falls
 * when somebody settles up, so its slope answers the only question worth
 * asking of it: is this getting better or worse. A per-month figure, or a
 * cumulative total of unpaid work, could only ever climb.
 *
 * It shares an axis with income, deliberately. A second
 * axis would let a few hundred owed draw as tall as a few thousand earned,
 * which is the one thing this pair of lines must never say. Sharing the scale
 * means the gap between them is the truth: normally a low line under a high
 * one, and worth alarm precisely when it starts to climb toward it.
 *
 * It is also the one line here that never gets a forecast. What people already
 * owe you is a fact, and guessing at it would be inventing a debt.
 *
 * History is what each month *earned*, not what was paid in it. A slow payer
 * should not make a busy month look thin.
 */
export function IncomeForecastChart({
  forecast,
  next,
  currency,
  totalOutstandingMinor,
}: {
  /** The month in progress. Its history is the completed months before it. */
  forecast: IncomeForecast
  /** The month after, so both estimates are visible at once. */
  next: IncomeForecast
  currency: string
  /** Everything still owed today, so the debt line ends where the tile does. */
  totalOutstandingMinor?: number
}) {
  const locale = useLocale()
  const major = (minor: number) => toMajor(minor, currency)

  const lastMonth = forecast.history.length - 1

  const history: Point[] = forecast.history.map((month, index) => ({
    label: formatMonth(month.month, { month: 'short', year: '2-digit' }),
    earned: major(month.earned_minor),
    // The estimate picks up exactly where the record stops, so the two lines
    // meet instead of leaving a gap the eye has to jump.
    estimate: index === lastMonth ? major(month.earned_minor) : null,
    band: index === lastMonth ? [major(month.earned_minor), major(month.earned_minor)] : null,
    owed: major(month.owed_balance_minor ?? 0),
  }))

  const estimate = (one: IncomeForecast, owed: number | null): Point => ({
    label: formatMonth(one.month, { month: 'short', year: '2-digit' }),
    earned: null,
    estimate: major(one.likely_minor),
    band: [major(one.low_minor), major(one.high_minor)],
    owed,
  })

  const data: Point[] = [
    ...history,
    // The month in progress is the last one anybody can be owed for, so the
    // debt line ends here, on the same figure the tile above reports.
    estimate(forecast, totalOutstandingMinor != null ? major(totalOutstandingMinor) : null),
    estimate(next, null),
  ]

  const config: ChartConfig = {
    earned: { label: 'Earned', color: 'var(--chart-1)' },
    estimate: { label: 'Estimate', color: 'var(--chart-1)' },
    band: { label: 'Range', color: 'var(--chart-1)' },
    owed: { label: 'Owed to you', color: 'var(--chart-4)' },
  }

  // Below two months of history the band is declared rather than measured, and
  // drawing it would dress a guess up as a measurement.
  const showBand = forecast.basis !== ForecastBasis.INSUFFICIENT_HISTORY

  return (
    <ChartContainer config={config} className="aspect-auto h-72 w-full">
      <ComposedChart data={data} margin={{ left: 4, right: 4, top: 8, bottom: 4 }}>
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
          yAxisId="money"
          tickLine={false}
          axisLine={false}
          width={52}
          tick={{ fontSize: 12 }}
          className="fill-muted-foreground"
          tickFormatter={(value: number) =>
            new Intl.NumberFormat(locale, { notation: 'compact' }).format(value)
          }
        />
        <ChartTooltip
          // A month has only some of these lines on it, and Recharts still
          // offers the ones it has no value for. Dropping them here keeps the
          // tooltip to what is actually under the cursor.
          content={({ active, label, payload }) => (
            <ChartTooltipContent
              active={active}
              label={label}
              payload={payload?.filter((item) => item.value != null)}
              formatter={(value, name) =>
                Array.isArray(value) ? (
                  <span className="text-muted-foreground">
                    {formatMoney(toMinor(Number(value[0]), currency), currency, locale)} to{' '}
                    {formatMoney(toMinor(Number(value[1]), currency), currency, locale)}
                  </span>
                ) : (
                  <span className="flex w-full justify-between gap-3">
                    <span className="text-muted-foreground">
                      {config[String(name)]?.label ?? name}
                    </span>
                    <span className="font-mono font-medium tabular-nums">
                      {formatMoney(toMinor(Number(value), currency), currency, locale)}
                    </span>
                  </span>
                )
              }
            />
          )}
        />
        {/* Where the record stops and the guessing starts. */}
        {history.length ? (
          <ReferenceLine
            yAxisId="money"
            x={history[lastMonth].label}
            stroke="var(--border)"
            strokeDasharray="4 4"
          />
        ) : null}
        {showBand ? (
          <Area
            yAxisId="money"
            dataKey="band"
            legendType="none"
            stroke="none"
            fill="var(--color-estimate)"
            fillOpacity={0.16}
            isAnimationActive={false}
            connectNulls={false}
          />
        ) : null}
        <Line
          yAxisId="money"
          dataKey="earned"
          type="monotone"
          stroke="var(--color-earned)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
          connectNulls={false}
          isAnimationActive={false}
        />
        <Line
          yAxisId="money"
          dataKey="estimate"
          legendType="none"
          type="monotone"
          stroke="var(--color-estimate)"
          strokeWidth={2}
          strokeDasharray="5 4"
          dot={{ r: 3 }}
          activeDot={{ r: 4 }}
          connectNulls={false}
          isAnimationActive={false}
        />
        <Line
          yAxisId="money"
          dataKey="owed"
          type="monotone"
          stroke="var(--color-owed)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4 }}
          connectNulls={false}
          isAnimationActive={false}
        />
        {/* Two lines on two different scales are unreadable without one. */}
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  )
}
