import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, MoreHorizontal, Pencil, Repeat, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import {
  transactionsDeleteTransaction,
  transactionsListTransactions,
  TransactionKind,
  type TransactionPublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { TransactionFilters } from '@/components/transactions/transaction-filters'
import { TransactionDialog } from '@/components/transactions/transaction-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAccounts } from '@/hooks/use-accounts'
import { useCategories } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/month'
import { emptyFilters, hasActiveFilters, toQuery, type Filters } from '@/lib/transaction-filters'

const PAGE_SIZE = 50

export function Component() {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<TransactionPublic | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<TransactionPublic | null>(null)

  const query = toQuery(filters)

  const transactions = useQuery({
    queryKey: ['transactions', query, page],
    queryFn: async () => {
      const { data, error } = await transactionsListTransactions({
        query: { ...query, skip: page * PAGE_SIZE, limit: PAGE_SIZE },
      })
      if (error) throw error
      return data
    },
  })

  // Names for the ids on each row, from lists that are cached anyway.
  const { data: accounts } = useAccounts({ includeArchived: true })
  const { data: categories } = useCategories()

  const accountNames = useMemo(
    () => new Map((accounts?.data ?? []).map((account) => [account.id, account.name])),
    [accounts],
  )
  const categoryNames = useMemo(
    () => new Map((categories?.data ?? []).map((category) => [category.id, category.name])),
    [categories],
  )

  const remove = useMutation({
    mutationFn: async (transaction: TransactionPublic) => {
      const { error } = await transactionsDeleteTransaction({
        path: { transaction_id: transaction.id },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      setDeleting(null)
      toast.success('Transaction deleted')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const total = transactions.data?.count ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <PageHeader
        title="Transactions"
        description="Everything your household spent, earned and moved."
      >
        <Button onClick={() => setCreating(true)}>Record a transaction</Button>
      </PageHeader>

      <Card>
        <CardContent>
          <TransactionFilters
            filters={filters}
            onChange={(next) => {
              setFilters(next)
              // A narrower list starts from its first page.
              setPage(0)
            }}
          />
        </CardContent>
      </Card>

      {transactions.isPending ? (
        <LoadingRows rows={6} />
      ) : transactions.isError ? (
        <ErrorState error={transactions.error} />
      ) : total === 0 ? (
        <EmptyState
          icon={ArrowLeftRight}
          title={
            hasActiveFilters(filters) ? 'Nothing matches those filters' : 'No transactions yet'
          }
          description={
            hasActiveFilters(filters)
              ? 'Widen the date range, or clear the filters to see everything.'
              : 'Record what you spent and earned, and the budgets and reports fill in from there.'
          }
        >
          {hasActiveFilters(filters) ? (
            <Button variant="outline" onClick={() => setFilters(emptyFilters)}>
              Clear filters
            </Button>
          ) : (
            <Button onClick={() => setCreating(true)}>Record your first transaction</Button>
          )}
        </EmptyState>
      ) : (
        <>
          <Card className="overflow-hidden py-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-28">Date</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Account</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {transactions.data.data.map((transaction) => {
                  const isTransfer = transaction.kind === TransactionKind.TRANSFER
                  const isIncome = transaction.kind === TransactionKind.INCOME

                  return (
                    <TableRow key={transaction.id}>
                      <TableCell className="text-muted-foreground whitespace-nowrap tabular-nums">
                        {formatDate(transaction.occurred_on, { day: 'numeric', month: 'short' })}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 font-medium">
                          {transaction.merchant ?? (isTransfer ? 'Transfer' : 'No description')}
                          {transaction.is_generated ? (
                            <Badge variant="secondary" className="gap-1">
                              <Repeat className="size-3" />
                              Recurring
                            </Badge>
                          ) : null}
                        </div>
                        {transaction.note ? (
                          <p className="text-muted-foreground line-clamp-1 text-xs">
                            {transaction.note}
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {isTransfer
                          ? '—'
                          : transaction.category_id
                            ? (categoryNames.get(transaction.category_id) ?? 'Unknown')
                            : 'Uncategorised'}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {accountNames.get(transaction.account_id) ?? 'Unknown'}
                        {isTransfer && transaction.counter_account_id ? (
                          <span>
                            {' '}
                            → {accountNames.get(transaction.counter_account_id) ?? 'Unknown'}
                          </span>
                        ) : null}
                      </TableCell>
                      <TableCell className="text-right">
                        {/* A transfer is neither spending nor income, so it is
                            shown plain rather than coloured either way. */}
                        <Money
                          minor={isIncome ? transaction.amount_minor : -transaction.amount_minor}
                          currency={currency}
                          signed={!isTransfer}
                          colored={!isTransfer}
                          className={isTransfer ? 'text-muted-foreground' : undefined}
                        />
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" aria-label="Manage transaction">
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setEditing(transaction)}>
                              <Pencil className="size-4" />
                              Edit
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              variant="destructive"
                              onClick={() => setDeleting(transaction)}
                            >
                              <Trash2 className="size-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </Card>

          <div className="flex items-center justify-between gap-4">
            <p className="text-muted-foreground text-sm">
              {total} {total === 1 ? 'transaction' : 'transactions'}
              {pageCount > 1 ? ` · page ${page + 1} of ${pageCount}` : null}
            </p>
            {pageCount > 1 ? (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((current) => current - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page + 1 >= pageCount}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            ) : null}
          </div>
        </>
      )}

      <TransactionDialog
        open={creating || editing !== null}
        transaction={editing}
        onOpenChange={(open) => {
          if (!open) {
            setCreating(false)
            setEditing(null)
          }
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this transaction?"
        description="Balances and reports update straight away. This cannot be undone."
        confirmLabel="Delete transaction"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}
