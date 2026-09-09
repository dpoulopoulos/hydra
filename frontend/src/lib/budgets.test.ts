import { describe, expect, it } from 'vitest'

import type { CategoryTreeNode } from '@/api'

import { removedLimits } from './budgets'

function category(id: string, name: string, children: CategoryTreeNode[] = []) {
  return {
    id,
    name,
    household_id: 'h',
    created_at: '2026-01-01T00:00:00Z',
    children,
  } as CategoryTreeNode
}

const TREE = [
  category('food', 'Food', [category('groceries', 'Groceries'), category('dining', 'Dining out')]),
  category('transport', 'Transport'),
]

describe('the limits a save would remove', () => {
  it('finds nothing when every budgeted category keeps its limit', () => {
    expect(removedLimits(TREE, ['groceries', 'transport'], ['groceries', 'transport'])).toEqual([])
  })

  it('names the category whose limit is gone', () => {
    expect(removedLimits(TREE, ['groceries', 'transport'], ['transport'])).toEqual(['Groceries'])
  })

  it('names them in the order the screen lists them, parents before their children', () => {
    expect(removedLimits(TREE, ['dining', 'transport', 'food', 'groceries'], [])).toEqual([
      'Food',
      'Groceries',
      'Dining out',
      'Transport',
    ])
  })

  it('ignores a category that had no limit to begin with', () => {
    expect(removedLimits(TREE, ['groceries'], [])).toEqual(['Groceries'])
  })

  it('ignores a budgeted category the tree does not hold', () => {
    // An archived category still carries its limit, and the editor never shows
    // it a field, so its limit is resent untouched rather than removed here.
    expect(removedLimits(TREE, ['archived'], [])).toEqual([])
  })
})
