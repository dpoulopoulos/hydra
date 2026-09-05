import { describe, expect, it } from 'vitest'

import { TransactionKind, TransactionSort } from '@/api'
import {
  ANY,
  type Filters,
  emptyFilters,
  hasActiveFilters,
  toQuery,
} from '@/lib/transaction-filters'

const ACCOUNT = '11111111-1111-1111-1111-111111111111'
const CATEGORY = '22222222-2222-2222-2222-222222222222'

/** The form's values with one control filled in. */
function filters(overrides: Partial<Filters> = {}): Filters {
  return { ...emptyFilters, ...overrides }
}

describe('emptyFilters', () => {
  it('narrows nothing', () => {
    expect(hasActiveFilters(emptyFilters)).toBe(false)
  })

  it('still asks for an order, since a list has to have one', () => {
    expect(emptyFilters.sort).toBe(TransactionSort['-DATE'])
    expect(toQuery(emptyFilters).sort).toBe(TransactionSort['-DATE'])
  })
})

describe('hasActiveFilters', () => {
  it.each([
    ['date_from', filters({ date_from: '2026-03-01' })],
    ['date_to', filters({ date_to: '2026-03-31' })],
    ['account_id', filters({ account_id: ACCOUNT })],
    ['category_id', filters({ category_id: CATEGORY })],
    ['kind', filters({ kind: TransactionKind.EXPENSE })],
    ['q', filters({ q: 'coffee' })],
  ])('reports %s as narrowing the list', (_name, value) => {
    expect(hasActiveFilters(value)).toBe(true)
  })

  it('does not count the order as a filter, because it removes no row', () => {
    expect(hasActiveFilters(filters({ sort: TransactionSort.AMOUNT }))).toBe(false)
  })
})

describe('toQuery', () => {
  // The list endpoint forbids unknown parameters and rejects an empty string
  // where it wants a date or a UUID, so a control left alone has to reach it
  // as null rather than as "" or as the picker's own "any".
  it('sends an untouched form as all nulls', () => {
    expect(toQuery(emptyFilters)).toEqual({
      date_from: null,
      date_to: null,
      account_id: null,
      category_id: null,
      kind: null,
      q: null,
      sort: TransactionSort['-DATE'],
    })
  })

  it('sends what was filled in', () => {
    expect(
      toQuery(
        filters({
          date_from: '2026-03-01',
          date_to: '2026-03-31',
          account_id: ACCOUNT,
          category_id: CATEGORY,
          kind: TransactionKind.EXPENSE,
          q: 'coffee',
          sort: TransactionSort.AMOUNT,
        }),
      ),
    ).toEqual({
      date_from: '2026-03-01',
      date_to: '2026-03-31',
      account_id: ACCOUNT,
      category_id: CATEGORY,
      kind: TransactionKind.EXPENSE,
      q: 'coffee',
      sort: TransactionSort.AMOUNT,
    })
  })

  it.each(['account_id', 'category_id', 'kind'] as const)(
    'turns the pickers own %s placeholder into null',
    (field) => {
      expect(toQuery(filters({ [field]: ANY }))[field]).toBeNull()
    },
  )

  it('keeps a search that is only spaces, since it is a term the API can take', () => {
    expect(toQuery(filters({ q: ' ' })).q).toBe(' ')
  })
})
