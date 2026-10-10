import { cn } from '@/lib/utils'

/**
 * The hydra mark: a lowercase h whose stem rises into a serpent's neck.
 *
 * The same drawing is public/favicon.svg, with the colours written out
 * because a favicon cannot read the theme.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn('size-8 shrink-0', className)}>
      <rect width="32" height="32" rx="7.5" className="fill-primary" />
      <g fill="none" strokeWidth="3.4" strokeLinecap="round" className="stroke-primary-foreground">
        <path d="M11 27V11c0-3.5 2-5 4.5-4.5" />
        <path d="M11 18c0-3.5 10-4.5 10 0v9" />
      </g>
      <g transform="translate(15.5 6.5) rotate(8) scale(1.15)">
        <path
          d="M-1.6-1.5C0-3.1 3.2-2.5 5.4-.5c.4.5.1 1.3-.5 1.4L1.2 1.9C-.4 2.3-1.6 1.2-1.6-1.5Z"
          className="fill-primary-foreground"
        />
        <circle cx="1.3" cy="-.5" r=".75" className="fill-primary" />
      </g>
    </svg>
  )
}
