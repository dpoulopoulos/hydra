import { Minus, TrendingDown, TrendingUp } from 'lucide-react'
import type { ReactNode } from 'react'

import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Money } from '@/components/money'
import { cn } from '@/lib/utils'

/**
 * A single figure with its label.
 *
 * A number is the right form when the job is one headline value, so these are
 * plain tiles rather than tiny charts. The figure is the largest thing on the
 * tile; everything else is set small and quiet around it.
 */
export function StatTile({
  label,
  minor,
  currency,
  signed = false,
  tone,
  hint,
  action,
  compare,
}: {
  label: string
  minor: number
  currency: string
  signed?: boolean
  /** Colour the figure when its direction is the point. */
  tone?: 'positive' | 'negative' | 'auto'
  hint?: ReactNode
  /** A small control for the figure itself, such as the span it covers. */
  action?: ReactNode
  /**
   * An earlier figure to set this one against, such as last month's. The
   * difference is shown under the figure, coloured by whether it is good news:
   * for a `negative` tone, such as money out, a fall is the good direction.
   */
  compare?: { minor: number; label: string }
}) {
  const color =
    tone === 'positive'
      ? 'text-positive'
      : tone === 'negative'
        ? 'text-negative'
        : tone === 'auto'
          ? minor < 0
            ? 'text-negative'
            : 'text-positive'
          : undefined

  const delta = compare ? minor - compare.minor : null

  return (
    <Card>
      <CardHeader className="gap-1">
        <CardDescription>{label}</CardDescription>
        {/* Beside the label, and only one row tall, so the figure below keeps
            the full width of the tile instead of being squeezed against it. */}
        {action ? <CardAction className="row-span-1">{action}</CardAction> : null}
        <CardTitle className={cn('col-span-full text-3xl font-semibold tracking-tight', color)}>
          <Money minor={minor} currency={currency} signed={signed} />
        </CardTitle>
        {delta !== null && compare ? (
          <Delta minor={delta} currency={currency} tone={tone} label={compare.label} />
        ) : null}
        {hint ? <p className="text-muted-foreground col-span-full text-xs">{hint}</p> : null}
      </CardHeader>
    </Card>
  )
}

/** The change since the compared figure, with an arrow for its direction. */
function Delta({
  minor,
  currency,
  tone,
  label,
}: {
  minor: number
  currency: string
  tone?: 'positive' | 'negative' | 'auto'
  label: string
}) {
  const Icon = minor > 0 ? TrendingUp : minor < 0 ? TrendingDown : Minus

  // Only judge the direction when the tile has said which way is good. A
  // tile with no tone, such as a plain total, gets a neutral reading.
  const good =
    tone === undefined || minor === 0 ? null : tone === 'negative' ? minor < 0 : minor > 0

  return (
    <p className="col-span-full flex flex-wrap items-center gap-x-1.5 text-xs">
      {/* The figure never breaks after its sign; only the "vs" may wrap. */}
      <span
        className={cn(
          'inline-flex items-center gap-1 whitespace-nowrap',
          good === null ? 'text-muted-foreground' : good ? 'text-positive' : 'text-negative',
        )}
      >
        <Icon className="size-3.5" aria-hidden />
        <Money minor={minor} currency={currency} signed />
      </span>
      <span className="text-muted-foreground">vs {label}</span>
    </p>
  )
}
