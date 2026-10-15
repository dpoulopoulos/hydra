import { Money } from '@/components/money'
import { cn } from '@/lib/utils'
import type { BudgetFigures } from '@/lib/budgets'
import { useLocale } from '@/lib/locale-context'
import { formatPercent } from '@/lib/money'

/**
 * One category's spending against its limit.
 *
 * The bar is not capped at the limit: going over is the case the whole screen
 * exists to show, so the overspend is drawn past the marker rather than
 * flattened against it.
 */
export function BudgetBar({
  row,
  currency,
  note,
}: {
  row: BudgetFigures
  currency: string
  /** Said after the name, about what the figure covers. */
  note?: string
}) {
  const locale = useLocale()
  const covers = note ?? (row.covers_subcategories ? 'and everything under it' : null)
  // Leave room to see the overspend, so a 150% bar does not fill the track.
  const scale = Math.max(1, row.progress)
  const spentWidth = (Math.min(row.progress, scale) / scale) * 100
  const limitMarker = (1 / scale) * 100

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
        <span className="font-medium">
          {row.category_name}
          {/* Dropped on a narrow screen: the row has no width to spare, and
              the rollup is already visible in the figure. */}
          {covers ? (
            <span className="text-muted-foreground ml-2 hidden text-xs font-normal sm:inline">
              {covers}
            </span>
          ) : null}
        </span>
        <span className="text-muted-foreground whitespace-nowrap tabular-nums">
          <Money minor={row.spent_minor} currency={currency} /> of{' '}
          <Money minor={row.limit_minor} currency={currency} />
        </span>
      </div>

      <div className="bg-muted relative h-2 overflow-hidden rounded-full">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            row.is_over_budget ? 'bg-negative' : 'bg-primary',
          )}
          style={{ width: `${spentWidth}%` }}
        />
        {row.progress > 1 ? (
          // Where the limit sat, once the bar has grown past it.
          <div
            aria-hidden
            className="bg-foreground/40 absolute top-0 h-full w-0.5"
            style={{ left: `${limitMarker}%` }}
          />
        ) : null}
      </div>

      <div className="flex justify-between text-xs">
        <span className={row.is_over_budget ? 'text-negative' : 'text-muted-foreground'}>
          {row.is_over_budget ? (
            <>
              <Money minor={-row.remaining_minor} currency={currency} /> over
            </>
          ) : (
            <>
              <Money minor={row.remaining_minor} currency={currency} /> left
            </>
          )}
        </span>
        <span className="text-muted-foreground tabular-nums">
          {formatPercent(row.progress, locale)}
        </span>
      </div>
    </div>
  )
}
