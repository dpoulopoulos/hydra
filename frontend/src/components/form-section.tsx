import type { ReactNode } from 'react'

/**
 * A titled group of fields, so ten controls read as three decisions.
 *
 * A long form is not made shorter by shrinking it; it is made shorter by
 * saying which questions belong together. The heading is quiet on purpose —
 * it is a signpost between groups, not a thing to read.
 */
export function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{title}</p>
      {children}
    </div>
  )
}
