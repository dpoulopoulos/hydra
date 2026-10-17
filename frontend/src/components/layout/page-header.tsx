import type { ReactNode } from 'react'

/**
 * The title block every page opens with, plus room for its main action.
 *
 * On a phone the heading steps down a size and the one-line description is
 * left out, so the action has room to sit beside the title instead of
 * dropping under it.
 */
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="space-y-1">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {description ? (
          <p className="text-muted-foreground hidden text-sm sm:block">{description}</p>
        ) : null}
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  )
}
