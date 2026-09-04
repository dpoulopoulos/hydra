import { ChevronLeft, ChevronRight } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { currentMonth, formatMonth, shiftMonth } from '@/lib/month'

/** Step through months, with a way back to this one. */
export function MonthPicker({
  month,
  onChange,
}: {
  month: string
  onChange: (month: string) => void
}) {
  const isCurrent = month === currentMonth()

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon"
        onClick={() => onChange(shiftMonth(month, -1))}
        aria-label="Previous month"
      >
        <ChevronLeft className="size-4" />
      </Button>
      <div className="min-w-36 text-center text-sm font-medium">{formatMonth(month)}</div>
      <Button
        variant="outline"
        size="icon"
        onClick={() => onChange(shiftMonth(month, 1))}
        aria-label="Next month"
      >
        <ChevronRight className="size-4" />
      </Button>
      {!isCurrent ? (
        <Button variant="ghost" size="sm" onClick={() => onChange(currentMonth())}>
          This month
        </Button>
      ) : null}
    </div>
  )
}
