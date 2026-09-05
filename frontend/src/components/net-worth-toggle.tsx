import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

/** Which part of net worth a figure is showing. */
export type NetWorthPart = 'bank' | 'brokerage' | 'assets' | 'total'

const OPTIONS: { value: NetWorthPart; label: string }[] = [
  { value: 'total', label: 'Everything' },
  { value: 'bank', label: 'Bank' },
  { value: 'brokerage', label: 'Brokerage' },
  { value: 'assets', label: 'Holdings' },
]

/**
 * Choose which part of net worth the tile shows.
 *
 * A dropdown rather than a row of buttons: four options in a row would be
 * wider than the figure they sit beside, and the tile is meant to lead with
 * the number.
 */
export function NetWorthToggle({
  value,
  onChange,
}: {
  value: NetWorthPart
  onChange: (value: NetWorthPart) => void
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as NetWorthPart)}>
      <SelectTrigger size="sm" aria-label="What Net worth covers" className="h-6 text-xs">
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="end">
        {OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
