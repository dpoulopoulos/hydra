import type { ReactNode } from 'react'

import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

/**
 * A labelled form control with room for a hint and an error.
 *
 * Written here rather than taken from the registry, which does not ship a form
 * component for this style. It wires the label, the hint and the error to the
 * control by id, so screen readers announce them together.
 *
 * Spaced with a gap rather than margins: a select renders a hidden native one
 * for form fallback, and a margin on that would leave the field taller than it
 * looks, which pushes the control up in a row aligned to its bottom.
 */
export function Field({
  id,
  label,
  hint,
  error,
  children,
  className,
}: {
  id: string
  label: string
  /** Shown under the control. Explains the input; never repeats the label. */
  hint?: ReactNode
  error?: string
  children: (props: {
    id: string
    'aria-describedby'?: string
    'aria-invalid'?: boolean
  }) => ReactNode
  className?: string
}) {
  const hintId = hint ? `${id}-hint` : undefined
  const errorId = error ? `${id}-error` : undefined
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <Label htmlFor={id}>{label}</Label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': Boolean(error) })}
      {error ? (
        <p id={errorId} className="text-destructive text-sm">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-muted-foreground text-sm">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

/** A whole-form error, for what the API refused rather than what a field got wrong. */
export function FormError({ message }: { message?: string | null }) {
  if (!message) return null
  return (
    <p role="alert" className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
      {message}
    </p>
  )
}
