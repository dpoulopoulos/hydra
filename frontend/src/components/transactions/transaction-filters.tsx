import { X } from 'lucide-react'

import { TransactionKind, TransactionSort } from '@/api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAccounts } from '@/hooks/use-accounts'
import { useCategoryTree } from '@/hooks/use-categories'
import { TRANSACTION_KIND_LABELS } from '@/lib/labels'
import { optionSource } from '@/lib/option-source'
import { ANY, emptyFilters, hasActiveFilters, type Filters } from '@/lib/transaction-filters'

/** Row counts to choose from. Thirty fills a screen without a long scroll. */
const PAGE_SIZES = [10, 30, 50, 100]

export function TransactionFilters({
  filters,
  onChange,
  pageSize,
  onPageSizeChange,
}: {
  filters: Filters
  onChange: (filters: Filters) => void
  /** Not a filter, but it belongs with the controls that shape the list. */
  pageSize: number
  onPageSizeChange: (pageSize: number) => void
}) {
  const accountsQuery = useAccounts({ includeArchived: true })
  const categoriesQuery = useCategoryTree({ includeArchived: true })

  // A filter offering nothing looks like a household with nothing to filter
  // by, so a refused list says so instead of quietly narrowing the choice.
  const accountSource = optionSource(accountsQuery, 'accounts')
  const categorySource = optionSource(categoriesQuery, 'categories')

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    onChange({ ...filters, [key]: value })

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <div className="space-y-2 sm:col-span-2 lg:col-span-1">
        <Label htmlFor="q">Search</Label>
        <Input
          id="q"
          value={filters.q}
          onChange={(event) => set('q', event.target.value)}
          placeholder="Merchant or note"
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="kind">Kind</Label>
        <Select value={filters.kind} onValueChange={(value) => set('kind', value)}>
          <SelectTrigger id="kind" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any kind</SelectItem>
            {Object.values(TransactionKind).map((kind) => (
              <SelectItem key={kind} value={kind}>
                {TRANSACTION_KIND_LABELS[kind]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="account">Account</Label>
        <Select
          value={filters.account_id}
          onValueChange={(value) => set('account_id', value)}
          disabled={accountSource.unavailable}
        >
          <SelectTrigger
            id="account"
            className="w-full"
            aria-describedby={accountSource.error ? 'account-error' : undefined}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any account</SelectItem>
            {accountSource.options.map((account) => (
              <SelectItem key={account.id} value={account.id}>
                {account.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <FilterError id="account-error" message={accountSource.error} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="category">Category</Label>
        <Select
          value={filters.category_id}
          onValueChange={(value) => set('category_id', value)}
          disabled={categorySource.unavailable}
        >
          <SelectTrigger
            id="category"
            className="w-full"
            aria-describedby={categorySource.error ? 'category-error' : undefined}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any category</SelectItem>
            {categorySource.options.map((parent) => (
              <div key={parent.id}>
                <SelectItem value={parent.id}>{parent.name}</SelectItem>
                {(parent.children ?? []).map((child) => (
                  <SelectItem key={child.id} value={child.id} className="pl-8">
                    {child.name}
                  </SelectItem>
                ))}
              </div>
            ))}
          </SelectContent>
        </Select>
        <FilterError id="category-error" message={categorySource.error} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="date_from">From</Label>
        <Input
          id="date_from"
          type="date"
          value={filters.date_from}
          onChange={(event) => set('date_from', event.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="date_to">To</Label>
        <Input
          id="date_to"
          type="date"
          value={filters.date_to}
          onChange={(event) => set('date_to', event.target.value)}
        />
      </div>

      <div className="space-y-2">
        <Label htmlFor="sort">Order</Label>
        <Select
          value={filters.sort}
          onValueChange={(value) => set('sort', value as TransactionSort)}
        >
          <SelectTrigger id="sort" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TransactionSort['-DATE']}>Newest first</SelectItem>
            <SelectItem value={TransactionSort.DATE}>Oldest first</SelectItem>
            <SelectItem value={TransactionSort['-AMOUNT']}>Largest first</SelectItem>
            <SelectItem value={TransactionSort.AMOUNT}>Smallest first</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="page-size">Rows per page</Label>
        <Select value={String(pageSize)} onValueChange={(value) => onPageSizeChange(Number(value))}>
          <SelectTrigger id="page-size" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PAGE_SIZES.map((size) => (
              <SelectItem key={size} value={String(size)}>
                {size}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {hasActiveFilters(filters) ? (
        <div className="flex items-end">
          <Button variant="ghost" onClick={() => onChange(emptyFilters)}>
            <X className="size-4" />
            Clear filters
          </Button>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Why a filter has nothing to offer.
 *
 * These controls are laid out as a label and a control rather than through
 * `Field`, which is for a form the user submits, so the message is rendered
 * here in the same voice and tied to the control by id.
 */
function FilterError({ id, message }: { id: string; message?: string }) {
  if (!message) return null
  return (
    <p id={id} className="text-destructive text-sm">
      {message}
    </p>
  )
}
