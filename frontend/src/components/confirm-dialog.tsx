import type { ReactNode } from 'react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { cn } from '@/lib/utils'

/**
 * Confirmation for something that cannot be undone.
 *
 * The confirm button repeats the verb of the action rather than saying "OK",
 * so the last thing read before committing is what will happen.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  pending,
  destructive = true,
  className,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description: ReactNode
  confirmLabel: string
  onConfirm: () => void
  pending?: boolean
  destructive?: boolean
  /** Widen the dialog where the description needs the room. */
  className?: string
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className={cn(className)}>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>Keep it</AlertDialogCancel>
          <AlertDialogAction
            // Through the prop rather than by pushing buttonVariants() into
            // className. AlertDialogAction renders a Button with asChild, so a
            // variant passed as a class is concatenated with the default one
            // rather than replacing it, and which of the two colours wins is
            // then down to the order of the generated stylesheet. That is how
            // this button ended up with the primary foreground on a
            // destructive background, which reads as disabled.
            variant={destructive ? 'destructive' : 'default'}
            disabled={pending}
            onClick={(event) => {
              // Closing is left to the caller, so the dialog can stay open if
              // the request is refused.
              event.preventDefault()
              onConfirm()
            }}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
