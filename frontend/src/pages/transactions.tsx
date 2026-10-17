import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeftRight, HandCoins, MoreHorizontal, Pencil, Repeat, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
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
import { Pagination } from '@/components/pagination'
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
import { useAccountCurrency, useAccounts } from '@/hooks/use-accounts'
import { useCategories } from '@/hooks/use-categories'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/month'
import { emptyFilters, hasActiveFilters, toQuery, type Filters } from '@/lib/transaction-filters'
import { cn } from '@/lib/utils'

/**
 * A tag on a row, such as "Recurring". Set small and grey, so it reads as a
 * note beside the merchant rather than competing with it.
 */
const ROW_BADGE = 'text-muted-foreground h-4 shrink-0 gap-1 px-1.5 text-[11px] font-normal'

export function Component() {
  // An amount is in the currency of the account it sits in.
  const currencyOf = useAccountCurrency()
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState<Filters>(emptyFilters)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(30)
  const [editing, setEditing] = useState<TransactionPublic | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<TransactionPublic | null>(null)

  const query = toQuery(filters)

  const transactions = useQuery({
    queryKey: ['transactions', query, page, pageSize],
    queryFn: async () => {
      const { data, error } = await transactionsListTransactions({
        query: { ...query, skip: page * pageSize, limit: pageSize },
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
            pageSize={pageSize}
            onPageSizeChange={(next) => {
              setPageSize(next)
              // Page four of fifty is not page four of ten.
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
                  const isExpense = transaction.kind === TransactionKind.EXPENSE
                  // The session holds the fee, so this row is a copy of it and
                  // the API refuses to edit or delete it. Offering both here
                  // would only produce an error toast.
                  const fromSession = transaction.income_session_id != null

                  return (
                    <TableRow key={transaction.id}>
                      <TableCell className="text-muted-foreground whitespace-nowrap tabular-nums">
                        {formatDate(transaction.occurred_on, { day: 'numeric', month: 'short' })}
                      </TableCell>
                      <TableCell>
                        {/* A transfer is money moved, not spent, so its row
                            is set quieter than the ones that are. */}
                        <div
                          className={cn(
                            'flex items-center gap-2',
                            isTransfer && 'text-muted-foreground',
                          )}
                        >
                          {transaction.merchant ?? (isTransfer ? 'Transfer' : 'No description')}
                          {fromSession ? (
                            <Badge variant="secondary" className={ROW_BADGE}>
                              <HandCoins className="size-3" />
                              Session
                            </Badge>
                          ) : transaction.is_generated ? (
                            <Badge variant="secondary" className={ROW_BADGE}>
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
                        {/* A transfer is neither spending nor income, so it
                            is shown plain rather than coloured either way:
                            negating it would print a minus the switched-off
                            sign cannot take back. */}
                        <Money
                          minor={isExpense ? -transaction.amount_minor : transaction.amount_minor}
                          currency={currencyOf(transaction.account_id)}
                          signed={!isTransfer}
                          colored={!isTransfer}
                          className={isTransfer ? 'text-muted-foreground' : undefined}
                        />
                        {/* A transfer into another currency arrived as a
                            different figure, which is the one the destination
                            account's balance moved by. */}
                        {transaction.counter_amount_minor != null ? (
                          <p className="text-muted-foreground text-xs">
                            →{' '}
                            <Money
                              minor={transaction.counter_amount_minor}
                              currency={currencyOf(transaction.counter_account_id)}
                              className="font-normal"
                            />
                          </p>
                        ) : null}
                      </TableCell>
                      <TableCell>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon-sm" aria-label="Manage transaction">
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {fromSession ? (
                              <DropdownMenuItem asChild>
                                <Link to="/clients">
                                  <HandCoins className="size-4" />
                                  Change it on the Clients page
                                </Link>
                              </DropdownMenuItem>
                            ) : (
                              <>
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
                              </>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
            {/* Inside the card, as a footer strip, so the count and the paging
                belong to the table rather than floating under it. */}
            <div className="bg-muted/30 border-t px-3 py-2">
              <Pagination
                page={page}
                pageSize={pageSize}
                total={total}
                onPageChange={setPage}
                noun="transaction"
              />
            </div>
          </Card>
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
