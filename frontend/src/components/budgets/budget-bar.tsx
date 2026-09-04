import type { BudgetProgressRow } from '@/api'
import { Money } from '@/components/money'
import { cn } from '@/lib/utils'
import { formatPercent } from '@/lib/money'

/**
 * One category's spending against its limit.
 *
 * The bar is not capped at the limit: going over is the case the whole screen
 * exists to show, so the overspend is drawn past the marker rather than
 * flattened against it.
 */
export function BudgetBar({ row, currency }: { row: BudgetProgressRow; currency: string }) {
  // Leave room to see the overspend, so a 150% bar does not fill the track.
  const scale = Math.max(1, row.progress)
  const spentWidth = (Math.min(row.progress, scale) / scale) * 100
  const limitMarker = (1 / scale) * 100

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="flex items-center gap-2 font-medium">
          {row.category_name}
          {row.covers_subcategories ? (
            <span className="text-muted-foreground text-xs font-normal">
              and everything under it
            </span>
          ) : null}
        </span>
        <span className="text-muted-foreground tabular-nums">
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
        <span className="text-muted-foreground tabular-nums">{formatPercent(row.progress)}</span>
      </div>
    </div>
  )
}
