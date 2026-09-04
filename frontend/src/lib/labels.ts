import { AccountType, CategoryKind, RecurrenceFrequency, TransactionKind } from '@/api'

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

export const FREQUENCY_LABELS: Record<string, string> = {
  [RecurrenceFrequency.WEEKLY]: 'Weekly',
  [RecurrenceFrequency.MONTHLY]: 'Monthly',
  [RecurrenceFrequency.YEARLY]: 'Yearly',
}

/** How often a rule repeats, in words, e.g. "Every 2 weeks". */
export function describeSchedule(
  frequency: string,
  interval: number,
  dayOfMonth?: number | null,
): string {
  const unit = { weekly: 'week', monthly: 'month', yearly: 'year' }[frequency] ?? frequency
  const every = interval === 1 ? `Every ${unit}` : `Every ${interval} ${unit}s`
  if (frequency === 'monthly' && dayOfMonth) return `${every} on day ${dayOfMonth}`
  return every
}
