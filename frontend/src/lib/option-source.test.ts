import { describe, expect, it } from 'vitest'

import { optionSource } from '@/lib/option-source'

const LOADED = { data: { data: [{ id: 'a' }, { id: 'b' }] }, isError: false, error: null }

describe('optionSource', () => {
  it('offers what the query returned', () => {
    const source = optionSource(LOADED, 'accounts')

    expect(source.options).toEqual([{ id: 'a' }, { id: 'b' }])
    expect(source.unavailable).toBe(false)
    expect(source.error).toBeUndefined()
  })

  it('offers nothing while the query is still on its way', () => {
    const source = optionSource({ data: undefined, isError: false, error: null }, 'accounts')

    expect(source.options).toEqual([])
    expect(source.unavailable).toBe(false)
    expect(source.error).toBeUndefined()
  })

  it('says the list is unavailable rather than empty when the query failed', () => {
    const source = optionSource(
      { data: undefined, isError: true, error: { detail: 'Accounts are down.' } },
      'accounts',
    )

    expect(source.options).toEqual([])
    expect(source.unavailable).toBe(true)
    expect(source.error).toBe('Could not load your accounts. Accounts are down.')
  })

  it('falls back to a reason of its own when the failure carries none', () => {
    const source = optionSource({ data: undefined, isError: true, error: null }, 'categories')

    expect(source.error).toBe('Could not load your categories. Try again in a moment.')
  })

  it('keeps the last list rather than emptying the picker on a failed refetch', () => {
    const source = optionSource({ ...LOADED, isError: true, error: null }, 'accounts')

    expect(source.options).toEqual([{ id: 'a' }, { id: 'b' }])
    expect(source.unavailable).toBe(false)
    expect(source.error).toBeUndefined()
  })
})
