import type { ReactNode } from 'react'

import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Money } from '@/components/money'
import { cn } from '@/lib/utils'

/**
 * A single figure with its label.
 *
 * A number is the right form when the job is one headline value, so these are
 * plain tiles rather than tiny charts.
 */
export function StatTile({
  label,
  minor,
  currency,
  signed = false,
  tone,
  hint,
  action,
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

  return (
    <Card>
      <CardHeader className="gap-1">
        <CardDescription>{label}</CardDescription>
        {/* Beside the label, and only one row tall, so the figure below keeps
            the full width of the tile instead of being squeezed against it. */}
        {action ? <CardAction className="row-span-1">{action}</CardAction> : null}
        <CardTitle className={cn('col-span-full text-2xl', color)}>
          <Money minor={minor} currency={currency} signed={signed} />
        </CardTitle>
        {hint ? <p className="text-muted-foreground col-span-full text-xs">{hint}</p> : null}
      </CardHeader>
    </Card>
  )
}
