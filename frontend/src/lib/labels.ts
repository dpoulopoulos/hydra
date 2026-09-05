import {
  AccountType,
  CategoryKind,
  InstrumentKind,
  RecurrenceFrequency,
  TradeSide,
  TransactionKind,
} from '@/api'

/**
 * Words for the enum values the API uses.
 *
 * Named for what people recognise rather than how the value is stored, so
 * "current" reads as "Current account" and "credit_card" as "Credit card".
 */
export const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  [AccountType.CASH]: 'Cash',
  [AccountType.CURRENT]: 'Current account',
  [AccountType.SAVINGS]: 'Savings',
  [AccountType.CREDIT_CARD]: 'Credit card',
  [AccountType.BROKERAGE]: 'Brokerage',
}

export const TRANSACTION_KIND_LABELS: Record<string, string> = {
  [TransactionKind.EXPENSE]: 'Expense',
  [TransactionKind.INCOME]: 'Income',
  [TransactionKind.TRANSFER]: 'Transfer',
}

export const CATEGORY_KIND_LABELS: Record<string, string> = {
  [CategoryKind.EXPENSE]: 'Expense',
  [CategoryKind.INCOME]: 'Income',
}

export const INSTRUMENT_KIND_LABELS: Record<string, string> = {
  [InstrumentKind.ETF]: 'ETF',
  [InstrumentKind.STOCK]: 'Share',
  [InstrumentKind.FUND]: 'Fund',
  [InstrumentKind.BOND]: 'Bond',
  [InstrumentKind.CRYPTO]: 'Crypto',
  [InstrumentKind.OTHER]: 'Other',
}

export const TRADE_SIDE_LABELS: Record<string, string> = {
  [TradeSide.BUY]: 'Bought',
  [TradeSide.SELL]: 'Sold',
}

export const FREQUENCY_LABELS: Record<string, string> = {
  [RecurrenceFrequency.WEEKLY]: 'Weekly',
  [RecurrenceFrequency.MONTHLY]: 'Monthly',
  [RecurrenceFrequency.YEARLY]: 'Yearly',
}

/**
 * How often a rule repeats, in words, e.g. "Every 2 weeks on day 15".
 *
 * Both the frequency and the interval have defaults on the wire, so they
 * arrive optional.
 */
export function describeSchedule(
  frequency: string | undefined,
  interval: number | undefined,
  dayOfMonth?: number | null,
): string {
  const every = frequency ?? 'monthly'
  const unit = { weekly: 'week', monthly: 'month', yearly: 'year' }[every] ?? every
  const count = interval ?? 1
  const phrase = count === 1 ? `Every ${unit}` : `Every ${count} ${unit}s`

  if (every === 'monthly' && dayOfMonth) return `${phrase} on day ${dayOfMonth}`
  return phrase
}
