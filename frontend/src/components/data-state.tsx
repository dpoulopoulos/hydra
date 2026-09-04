import { AlertCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/api'

/** What a screen shows while its data is still on the way. */
export function LoadingRows({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-12 w-full" />
      ))}
    </div>
  )
}

/**
 * What a screen shows when the API refused.
 *
 * The backend writes its domain errors for a reader, so they are shown as
 * they came rather than replaced with something vaguer.
 */
export function ErrorState({
  error,
  title = 'That did not load',
}: {
  error: unknown
  title?: string
}) {
  return (
    <Alert variant="destructive">
      <AlertCircle className="size-4" />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>{errorMessage(error)}</AlertDescription>
    </Alert>
  )
}

/** What a screen shows when there is nothing yet. An invitation, not an apology. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  children,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed px-6 py-14 text-center">
      {Icon ? <Icon className="text-muted-foreground size-8" /> : null}
      <div className="space-y-1">
        <p className="font-medium">{title}</p>
        {description ? (
          <p className="text-muted-foreground mx-auto max-w-sm text-sm">{description}</p>
        ) : null}
      </div>
      {children}
    </div>
  )
}
