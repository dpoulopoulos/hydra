import { Loader2 } from 'lucide-react'
import type { ComponentProps } from 'react'

import { Button } from '@/components/ui/button'

/**
 * A submit button that shows it is working.
 *
 * The label stays the same while pending, so the action keeps one name from
 * click to result.
 */
export function SubmitButton({
  pending,
  children,
  ...props
}: ComponentProps<typeof Button> & { pending?: boolean }) {
  return (
    <Button type="submit" disabled={pending || props.disabled} {...props}>
      {pending ? <Loader2 className="size-4 animate-spin" /> : null}
      {children}
    </Button>
  )
}
