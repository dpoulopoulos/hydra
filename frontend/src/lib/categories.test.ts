import { describe, expect, it } from 'vitest'

import { archiveMessage } from './categories'

describe('archiveMessage', () => {
  it('says a top level category takes its subcategories with it', () => {
    expect(archiveMessage({ name: 'Food & Drink', parentId: null, archived: true })).toBe(
      'Food & Drink archived, along with anything under it',
    )
  })

  it('says a restored top level category brings its subcategories back', () => {
    expect(archiveMessage({ name: 'Food & Drink', parentId: null, archived: false })).toBe(
      'Food & Drink restored, along with anything archived with it',
    )
  })

  it('says nothing about a branch for a subcategory, which has none', () => {
    const parentId = '11111111-1111-1111-1111-111111111111'

    expect(archiveMessage({ name: 'Groceries', parentId, archived: true })).toBe(
      'Groceries archived',
    )
    expect(archiveMessage({ name: 'Groceries', parentId, archived: false })).toBe(
      'Groceries restored',
    )
  })
})
