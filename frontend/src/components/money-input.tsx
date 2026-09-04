import type { ComponentProps } from 'react'

import { Input } from '@/components/ui/input'

type MoneyInputProps = ComponentProps<typeof Input> & {
  /** Shown as a prefix, so the field says which currency it is in. */
  currency?: string
}

/**
 * An amount field.
 *
 * People type major units, "42.50", while the API takes minor ones, 4250. The
 * field submits the string as typed and the form's schema converts it, so no
 * screen has to remember the conversion.
 */
export function MoneyInput({ currency = 'EUR', className, ...props }: MoneyInputProps) {
  return (
    <div className="relative">
      <span className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-sm">
        {currency}
      </span>
      <Input
        type="text"
        inputMode="decimal"
        autoComplete="off"
        placeholder="0.00"
        className={['pl-12 text-right tabular-nums', className].filter(Boolean).join(' ')}
        {...props}
      />
    </div>
  )
}
