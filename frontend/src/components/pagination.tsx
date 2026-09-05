import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// The sizes on offer when a table lets you choose. Kept unexported: a constant
// leaving a component file costs fast refresh, and nothing outside needs it.
const PAGE_SIZES = [10, 20, 50, 100]

/**
 * The row under a table: how many rows there are, and how to move between
 * pages.
 *
 * The page controls only appear once there is more than one page, so a short
 * table is not framed by buttons that do nothing. The count is always there,
 * because "how many are there" is worth an answer either way.
 *
 * How many rows fit on a page is a preference rather than a filter, so where a
 * table offers the choice it sits down here beside the paging it governs,
 * rather than up among the things that decide which rows are shown at all.
 */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  noun,
  plural,
  id,
}: {
  /** Zero based, as the API's skip is. */
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  /** Offer the reader the choice of page size. Omit to keep it fixed. */
  onPageSizeChange?: (pageSize: number) => void
  /** What one row is, e.g. "account". */
  noun: string
  /** Its plural, when adding an s will not do. */
  plural?: string
  /** Needed only when more than one of these shares a page, for the label. */
  id?: string
}) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const label = total === 1 ? noun : (plural ?? `${noun}s`)

  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div className="flex flex-wrap items-center gap-4">
        <p className="text-muted-foreground text-sm">
          {total} {label}
          {pageCount > 1 ? ` · page ${page + 1} of ${pageCount}` : null}
        </p>
        {onPageSizeChange ? (
          <div className="flex items-center gap-2">
            <Label htmlFor={`${id ?? 'table'}-page-size`} className="text-muted-foreground text-sm">
              Rows
            </Label>
            <Select
              value={String(pageSize)}
              onValueChange={(value) => onPageSizeChange(Number(value))}
            >
              <SelectTrigger id={`${id ?? 'table'}-page-size`} size="sm" className="w-20">
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper" align="start">
                {PAGE_SIZES.map((size) => (
                  <SelectItem key={size} value={String(size)}>
                    {size}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
      </div>
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
