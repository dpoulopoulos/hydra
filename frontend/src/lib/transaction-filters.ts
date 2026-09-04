import { TransactionKind, TransactionSort } from '@/api'

/** The value a picker uses to mean "do not narrow by this". */
export const ANY = 'any'

export type Filters = {
  date_from: string
  date_to: string
  account_id: string
  category_id: string
  kind: string
  q: string
  sort: TransactionSort
}

export const emptyFilters: Filters = {
  date_from: '',
  date_to: '',
  account_id: ANY,
  category_id: ANY,
  kind: ANY,
  q: '',
  sort: TransactionSort['-DATE'],
}

/** True when anything is narrowing the list. */
export function hasActiveFilters(filters: Filters): boolean {
  return (
    filters.date_from !== '' ||
    filters.date_to !== '' ||
    filters.account_id !== ANY ||
    filters.category_id !== ANY ||
    filters.kind !== ANY ||
    filters.q !== ''
  )
}

/**
 * Turn the form's values into the query the API takes.
 *
 * The list endpoint forbids unknown parameters, so an empty control has to
 * become null rather than an empty string.
 */
export function toQuery(filters: Filters) {
  return {
    date_from: filters.date_from || null,
    date_to: filters.date_to || null,
    account_id: filters.account_id === ANY ? null : filters.account_id,
    category_id: filters.category_id === ANY ? null : filters.category_id,
    kind: filters.kind === ANY ? null : (filters.kind as TransactionKind),
    q: filters.q || null,
    sort: filters.sort,
  }
}
