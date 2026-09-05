import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Which month an estimate covers: the one in progress, or the one after it. */
export type MonthScope = 'this' | 'next'

const OPTIONS: { value: MonthScope; label: string }[] = [
  { value: 'this', label: 'This' },
  { value: 'next', label: 'Next' },
]

/**
 * A two-way switch between this month and next.
 *
 * Small enough to sit inside a stat tile, so the estimate can change which
 * month it covers without the rest of the page following it. Built like
 * PeriodToggle, which does the same job for a month against its year.
 */
export function MonthScopeToggle({
  value,
  onChange,
  disabled,
}: {
  value: MonthScope
  onChange: (value: MonthScope) => void
  disabled?: boolean
}) {
  return (
    <div
      className="bg-muted inline-flex w-fit gap-0.5 rounded-md p-0.5"
      role="group"
      aria-label="Which month"
    >
      {OPTIONS.map((option) => (
        <Button
          key={option.value}
          type="button"
          size="sm"
          variant="ghost"
          aria-pressed={value === option.value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            'h-6 px-2 text-xs font-normal',
            value === option.value && 'bg-background shadow-sm',
          )}
        >
          {option.label}
        </Button>
      ))}
    </div>
  )
}
