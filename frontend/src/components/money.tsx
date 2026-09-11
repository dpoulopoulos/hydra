import { useLocale } from '@/lib/locale-context'
import { cn } from '@/lib/utils'
import { formatMoney, formatSignedMoney } from '@/lib/money'

/**
 * A monetary figure.
 *
 * Tabular numerals so columns of amounts line up, and colour only where the
 * direction of the money is the point.
 */
export function Money({
  minor,
  currency = 'EUR',
  signed = false,
  colored = false,
  className,
}: {
  minor: number
  currency?: string
  /** Show a leading + for money in. */
  signed?: boolean
  /** Colour by direction: pine for money in, rose for money out. */
  colored?: boolean
  className?: string
}) {
  const locale = useLocale()

  return (
    <span
      className={cn(
        'font-medium tabular-nums',
        colored && (minor < 0 ? 'text-negative' : minor > 0 ? 'text-positive' : undefined),
        className,
      )}
    >
      {signed ? formatSignedMoney(minor, currency, locale) : formatMoney(minor, currency, locale)}
    </span>
  )
}
