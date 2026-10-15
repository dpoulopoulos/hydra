import { describe, expect, it } from 'vitest'

import type { BudgetProgressRow, CategoryTreeNode } from '@/api'

import { groupBudgetRows, removedLimits } from './budgets'

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

function row(
  categoryId: string,
  parentId: string | null,
  limitMinor: number,
  spentMinor: number,
): BudgetProgressRow {
  return {
    budget_id: `budget-${categoryId}`,
    category_id: categoryId,
    category_name: categoryId,
    parent_id: parentId,
    covers_subcategories: false,
    limit_minor: limitMinor,
    spent_minor: spentMinor,
    remaining_minor: limitMinor - spentMinor,
    progress: spentMinor / limitMinor,
    is_over_budget: spentMinor > limitMinor,
  }
}

describe('gathering budgeted subcategories under their parent', () => {
  it('gives the parent its subcategories added up', () => {
    const groups = groupBudgetRows(
      [row('groceries', 'food', 30000, 15000), row('dining', 'food', 10000, 12000)],
      TREE,
    )

    expect(groups).toHaveLength(1)
    expect(groups[0]).toMatchObject({
      kind: 'parent',
      categoryId: 'food',
      total: {
        category_name: 'Food',
        limit_minor: 40000,
        spent_minor: 27000,
        remaining_minor: 13000,
        progress: 0.675,
        is_over_budget: false,
      },
    })
    expect(groups[0].kind === 'parent' && groups[0].rows.map((r) => r.category_id)).toEqual([
      'groceries',
      'dining',
    ])
  })

  it('leaves a budget with no parent on its own', () => {
    expect(groupBudgetRows([row('transport', null, 10000, 5000)], TREE)).toEqual([
      { kind: 'row', row: row('transport', null, 10000, 5000) },
    ])
  })

  it('leaves a subcategory on its own when the tree does not hold its parent', () => {
    const groups = groupBudgetRows([row('orphan', 'gone', 10000, 0)], TREE)
    expect(groups.map((group) => group.kind)).toEqual(['row'])
  })

  it('places a parent by its own total, most of the limit used first', () => {
    const groups = groupBudgetRows(
      [
        row('groceries', 'food', 10000, 9000),
        row('transport', null, 10000, 5000),
        row('dining', 'food', 10000, 0),
      ],
      TREE,
    )

    // Food is at 45%, below Transport at 50%, though Groceries alone is at 90%.
    expect(
      groups.map((group) => (group.kind === 'row' ? group.row.category_id : group.categoryId)),
    ).toEqual(['transport', 'food'])
  })
})
