import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

/**
 * The frame around every screen someone sees before they are signed in.
 *
 * One centred card on a tinted ground, so sign-in, sign-up, password reset and
 * the invitation pages all feel like the same short errand.
 */
export function AuthLayout({
  title,
  description,
  children,
  footer,
}: {
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <main className="relative flex min-h-svh flex-col items-center justify-center gap-6 overflow-hidden p-6">
      {/* A soft wash of the accent, so the page is not a bare white sheet. */}
      <div
        aria-hidden
        className="from-primary/8 pointer-events-none absolute inset-0 bg-gradient-to-br via-transparent to-transparent"
      />
      <div
        aria-hidden
        className="bg-primary/10 pointer-events-none absolute -top-32 -right-24 size-80 rounded-full blur-3xl"
      />

      <Link to="/" className="relative flex items-center gap-2 font-semibold">
        <span className="bg-primary text-primary-foreground flex size-8 items-center justify-center rounded-lg">
          h
        </span>
        hydra
      </Link>

      <Card className="relative w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>

      {footer ? (
        <p className="text-muted-foreground relative text-center text-sm">{footer}</p>
      ) : null}
    </main>
  )
}
