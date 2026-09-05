import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * A small button that copies a value to the clipboard.
 *
 * The tick replaces the icon for a moment, so the click is acknowledged where
 * the user is already looking rather than only in a toast at the edge of the
 * screen.
 */
export function CopyButton({
  value,
  label,
  className,
}: {
  /** The text placed on the clipboard. */
  value: string
  /** What was copied, named the way it is written elsewhere, e.g. "IBAN". */
  label: string
  className?: string
}) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), 1500)
    return () => clearTimeout(timer)
  }, [copied])

  const copy = async () => {
    try {
      // Only available over HTTPS and on localhost. Anywhere else the browser
      // leaves it undefined rather than throwing, so check before calling.
      if (!navigator.clipboard) throw new Error('The browser did not allow copying.')
      await navigator.clipboard.writeText(value)
      setCopied(true)
    } catch {
      toast.error(`Could not copy the ${label}.`)
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className={cn('size-6', className)}
      aria-label={copied ? `${label} copied` : `Copy ${label}`}
      onClick={() => void copy()}
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </Button>
  )
}
