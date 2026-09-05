/**
 * Category helpers.
 */

/** What to tell the user after archiving or restoring a category. */
export function archiveMessage({
  name,
  parentId,
  archived,
}: {
  name: string
  parentId: string | null
  archived: boolean
}): string {
  const verb = archived ? 'archived' : 'restored'

  // Archiving a top level category archives its subcategories, and restoring
  // it brings back the ones that archive took down. Both are worth saying:
  // the list only shows the branch the user is looking at, so a change to the
  // rest of it is otherwise invisible until they switch "Show archived".
  if (parentId !== null) {
    return `${name} ${verb}`
  }

  return archived
    ? `${name} archived, along with anything under it`
    : `${name} restored, along with anything archived with it`
}
