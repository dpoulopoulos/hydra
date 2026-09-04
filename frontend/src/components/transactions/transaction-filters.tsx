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
import { ANY, emptyFilters, hasActiveFilters, type Filters } from '@/lib/transaction-filters'
import { TRANSACTION_KIND_LABELS } from '@/lib/labels'

export function TransactionFilters({
  filters,
  onChange,
}: {
  filters: Filters
  onChange: (filters: Filters) => void
}) {
  const { data: accounts } = useAccounts({ includeArchived: true })
  const { data: categories } = useCategoryTree({ includeArchived: true })

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
        <Select value={filters.account_id} onValueChange={(value) => set('account_id', value)}>
          <SelectTrigger id="account" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any account</SelectItem>
            {(accounts?.data ?? []).map((account) => (
              <SelectItem key={account.id} value={account.id}>
                {account.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="category">Category</Label>
        <Select value={filters.category_id} onValueChange={(value) => set('category_id', value)}>
          <SelectTrigger id="category" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Any category</SelectItem>
            {(categories?.data ?? []).map((parent) => (
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
