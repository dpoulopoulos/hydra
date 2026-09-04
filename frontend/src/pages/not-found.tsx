import { Link } from 'react-router'

import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-muted-foreground font-mono text-sm">404</p>
      <h1 className="text-2xl font-semibold tracking-tight">There is nothing at this address</h1>
      <p className="text-muted-foreground max-w-sm text-sm">
        The link may be out of date, or the page may have moved.
      </p>
      <Button asChild>
        <Link to="/">Go to the dashboard</Link>
      </Button>
    </main>
  )
}
