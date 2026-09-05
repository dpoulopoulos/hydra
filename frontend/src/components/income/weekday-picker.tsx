import { Button } from '@/components/ui/button'
import { WEEKDAYS } from '@/lib/cadence'
import { cn } from '@/lib/utils'

/**
 * Which days of the week a client is seen on.
 *
 * Seven toggles rather than a multi-select: a week is short, the days have a
 * fixed order everyone already knows, and picking four of them should take
 * four clicks and no reading.
 *
 * Choosing none is a real answer — the schedule then keeps the weekday it was
 * pinned to — so the field is never in an invalid state and needs no error.
 */
export function WeekdayPicker({
  value,
  onChange,
  id,
}: {
  /** Days of the week, Monday as 0. */
  value: number[]
  onChange: (value: number[]) => void
  id?: string
}) {
  function toggle(day: number) {
    onChange(
      value.includes(day)
        ? value.filter((one) => one !== day)
        : [...value, day].sort((a, b) => a - b),
    )
  }

  return (
    <div id={id} className="flex flex-wrap gap-1" role="group" aria-label="Days of the week">
      {WEEKDAYS.map((weekday) => {
        const picked = value.includes(weekday.day)

        return (
          <Button
            key={weekday.day}
            type="button"
            size="sm"
            variant={picked ? 'default' : 'outline'}
            aria-pressed={picked}
            aria-label={weekday.long}
            onClick={() => toggle(weekday.day)}
            className={cn('w-11 px-0 font-normal', picked && 'font-medium')}
          >
            {weekday.short}
          </Button>
        )
      })}
    </div>
  )
}
