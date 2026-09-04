import { Button } from '@/components/ui/button'

/**
 * The row under a table: how many rows there are, and how to move between
 * pages.
 *
 * The page controls only appear once there is more than one page, so a short
 * table is not framed by buttons that do nothing. The count is always there,
 * because "how many are there" is worth an answer either way.
 */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  noun,
  plural,
}: {
  /** Zero based, as the API's skip is. */
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  /** What one row is, e.g. "account". */
  noun: string
  /** Its plural, when adding an s will not do. */
  plural?: string
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const label = total === 1 ? noun : (plural ?? `${noun}s`)

  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <p className="text-muted-foreground text-sm">
        {total} {label}
        {pageCount > 1 ? ` · page ${page + 1} of ${pageCount}` : null}
      </p>
      {pageCount > 1 ? (
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page === 0}
            onClick={() => onPageChange(page - 1)}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page + 1 >= pageCount}
            onClick={() => onPageChange(page + 1)}
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  )
}
