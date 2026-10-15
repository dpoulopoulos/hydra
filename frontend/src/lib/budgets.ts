import type { BudgetProgressRow, CategoryTreeNode } from '@/api'

/**
 * The categories a save is about to leave unbudgeted.
 *
 * `PUT /budgets/bulk` replaces the month with the set it is given, so a
 * category left out of that set loses its limit. This names the ones that
 * would, so the user can be shown the scale of what emptying a field does
 * before it happens.
 *
 * The names come back in the order the tree lists them, parents before their
 * own children, so the list reads down the screen the fields were cleared on.
 * A budgeted category the tree does not hold is skipped: the editor never
 * gives it a field, so its limit is resent as it stands rather than removed.
 */
export function removedLimits(
  tree: CategoryTreeNode[],
  budgeted: Iterable<string>,
  keeping: Iterable<string>,
): string[] {
  const had = new Set(budgeted)
  const keeps = new Set(keeping)

  return tree
    .flatMap((parent) => [parent, ...(parent.children ?? [])])
    .filter((category) => had.has(category.id) && !keeps.has(category.id))
    .map((category) => category.name)
}

/** What a budget bar draws: a limit, what was spent against it, and how far along it is. */
export type BudgetFigures = Pick<
  BudgetProgressRow,
  | 'category_name'
  | 'covers_subcategories'
  | 'limit_minor'
  | 'spent_minor'
  | 'remaining_minor'
  | 'progress'
  | 'is_over_budget'
>

/** One entry on the budgets screen: a budget on its own, or a parent over its budgeted subcategories. */
export type BudgetGroup =
  | { kind: 'row'; row: BudgetProgressRow }
  | { kind: 'parent'; categoryId: string; total: BudgetFigures; rows: BudgetProgressRow[] }

/**
 * The figures of a limit, worked out the way the report works them out.
 *
 * A limit of nothing is a real choice, so any spending against it counts as
 * fully used rather than dividing by zero.
 */
export function budgetFigures(
  categoryName: string,
  limitMinor: number,
  spentMinor: number,
): BudgetFigures {
  return {
    category_name: categoryName,
    covers_subcategories: false,
    limit_minor: limitMinor,
    spent_minor: spentMinor,
    remaining_minor: limitMinor - spentMinor,
    progress: limitMinor
      ? Math.round((spentMinor / limitMinor) * 10_000) / 10_000
      : spentMinor
        ? 1
        : 0,
    is_over_budget: spentMinor > limitMinor,
  }
}

/**
 * Gather the budgeted subcategories of a month under their parents.
 *
 * A parent and its subcategory are never budgeted together, so a parent whose
 * subcategories carry the limits has no row of its own. It gets one here: its
 * subcategories' limits and spending added up. Only what is budgeted is added,
 * so the parent's figure is the sum of the rows under it and nothing is
 * counted twice. Spending filed on the parent itself stays unbudgeted.
 *
 * The groups keep the report's order, most of the limit used first, a parent
 * placed by its own total. A subcategory whose parent the tree does not hold
 * is left on its own rather than dropped.
 */
export function groupBudgetRows(
  rows: BudgetProgressRow[],
  tree: CategoryTreeNode[],
): BudgetGroup[] {
  const parentNames = new Map(tree.map((parent) => [parent.id, parent.name]))
  const children = new Map<string, BudgetProgressRow[]>()
  const groups: BudgetGroup[] = []

  for (const row of rows) {
    if (row.parent_id && parentNames.has(row.parent_id)) {
      const siblings = children.get(row.parent_id)
      if (siblings) siblings.push(row)
      else children.set(row.parent_id, [row])
    } else {
      groups.push({ kind: 'row', row })
    }
  }

  for (const [parentId, budgeted] of children) {
    groups.push({
      kind: 'parent',
      categoryId: parentId,
      total: budgetFigures(
        parentNames.get(parentId) ?? '',
        budgeted.reduce((sum, row) => sum + row.limit_minor, 0),
        budgeted.reduce((sum, row) => sum + row.spent_minor, 0),
      ),
      rows: budgeted,
    })
  }

  const progressOf = (group: BudgetGroup) =>
    group.kind === 'row' ? group.row.progress : group.total.progress

  return groups.sort((a, b) => progressOf(b) - progressOf(a))
}
