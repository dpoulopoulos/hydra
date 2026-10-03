import type { GoalPublic } from '@/api'
import { Money } from '@/components/money'
import { useLocale } from '@/lib/locale-context'
import { formatPercent } from '@/lib/money'
import { cn } from '@/lib/utils'

/**
 * How far a goal has come.
 *
 * Capped at a full bar: unlike a budget, going past the target is good news,
 * and the percentage beside it already says by how much.
 *
 * A goal marked reached shows the most it ever held rather than what it holds
 * now. Reaching a goal usually means spending it, and a reached goal drawn as
 * an empty bar reads as one that never got anywhere.
 */
export function GoalBar({ goal }: { goal: GoalPublic }) {
  const locale = useLocale()
  const shown = goal.achieved_at ? goal.peak_saved_minor : goal.saved_minor
  const progress = shown / goal.target_minor
  const width = Math.max(0, Math.min(progress, 1)) * 100
  const reached = shown >= goal.target_minor

  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
        <span className="text-muted-foreground whitespace-nowrap tabular-nums">
          <Money minor={shown} currency={goal.currency_code} /> of{' '}
          <Money minor={goal.target_minor} currency={goal.currency_code} />
        </span>
        <span className="text-muted-foreground tabular-nums">
          {formatPercent(progress, locale)}
        </span>
      </div>
      <div
        className="bg-muted h-2 overflow-hidden rounded-full"
        role="progressbar"
        aria-label={`${goal.name} progress`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(width)}
      >
        <div
          className={cn(
            'h-full rounded-full transition-all',
            reached ? 'bg-positive' : 'bg-primary',
          )}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  )
}
