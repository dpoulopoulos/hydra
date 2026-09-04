import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Whether a figure covers the chosen month or the whole calendar year. */
export type Period = 'month' | 'year'

const OPTIONS: { value: Period; label: string }[] = [
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
]

/**
 * A two-way switch between a month and its year.
 *
 * Small enough to sit inside a stat tile, so one figure can change its span
 * without the rest of the page following it.
 */
export function PeriodToggle({
  value,
  onChange,
  disabled,
  label,
}: {
  value: Period
  onChange: (value: Period) => void
  disabled?: boolean
  label: string
}) {
  return (
    <div
      className="bg-muted inline-flex w-fit gap-0.5 rounded-md p-0.5"
      role="group"
      aria-label={label}
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
