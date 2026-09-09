import type { CategoryTreeNode } from '@/api'

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
