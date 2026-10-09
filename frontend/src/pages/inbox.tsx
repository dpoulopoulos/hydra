import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Inbox } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'

import {
  BankDirection,
  bankListBankInbox,
  bankReopenBankTransaction,
  BankReviewStatus,
  bankSkipBankTransaction,
  type BankTransactionPublic,
} from '@/api'
import { AcceptDialog } from '@/components/bank/accept-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { Pagination } from '@/components/pagination'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAccounts } from '@/hooks/use-accounts'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/month'

const PAGE_SIZE = 50

const EMPTY: Record<BankReviewStatus, { title: string; description: string }> = {
  pending: {
    title: 'Nothing to review',
    description: 'New transactions from your banks land here. Sync a bank to check for more.',
  },
  skipped: {
    title: 'Nothing skipped',
    description: 'What you skip waits here, in case you want it after all.',
  },
  accepted: {
    title: 'Nothing accepted yet',
    description: 'What you accept goes into your ledger, and is listed here too.',
  },
}

export function Component() {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<BankReviewStatus>(BankReviewStatus.PENDING)
  const [page, setPage] = useState(0)
  const [accepting, setAccepting] = useState<BankTransactionPublic | null>(null)

  const rows = useQuery({
    queryKey: ['bank', 'inbox', status, page],
    queryFn: async () => {
      const { data, error } = await bankListBankInbox({
        query: { status, skip: page * PAGE_SIZE, limit: PAGE_SIZE },
      })
      if (error) throw error
      return data
    },
  })

  const { data: accounts } = useAccounts({ includeArchived: true })
  const accountName = (id: string | null | undefined) =>
    id ? accounts?.data.find((account) => account.id === id)?.name : undefined

  // Skipping and putting back are one click each and change nothing in the
  // ledger, so neither asks first.
  const review = useMutation({
    mutationFn: async ({
      row,
      action,
    }: {
      row: BankTransactionPublic
      action: 'skip' | 'reopen'
    }) => {
      const call = action === 'skip' ? bankSkipBankTransaction : bankReopenBankTransaction
      const { error } = await call({ path: { bank_transaction_id: row.id } })
      if (error) throw error
      return action
    },
    onSuccess: (action) => {
      void queryClient.invalidateQueries({ queryKey: ['bank', 'inbox'] })
      toast.success(action === 'skip' ? 'Skipped' : 'Back in the inbox')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const total = rows.data?.count ?? 0

  return (
    <>
      <PageHeader
        title="Inbox"
        description="Transactions your banks sent. Accept one to put it in your ledger, or skip it."
      >
        <Button variant="outline" asChild>
          <Link to="/settings/bank">Manage banks</Link>
        </Button>
      </PageHeader>

      <Tabs
        value={status}
        onValueChange={(value) => {
          setStatus(value as BankReviewStatus)
          setPage(0)
        }}
      >
        <TabsList>
          <TabsTrigger value={BankReviewStatus.PENDING}>To review</TabsTrigger>
          <TabsTrigger value={BankReviewStatus.SKIPPED}>Skipped</TabsTrigger>
          <TabsTrigger value={BankReviewStatus.ACCEPTED}>Accepted</TabsTrigger>
        </TabsList>
      </Tabs>

      {rows.isPending ? (
        <LoadingRows rows={6} />
      ) : rows.isError ? (
        <ErrorState error={rows.error} />
      ) : total === 0 ? (
        <EmptyState
          icon={Inbox}
          title={EMPTY[status].title}
          description={EMPTY[status].description}
        />
      ) : (
        <>
          <Card className="overflow-hidden py-0">
            <div className="overflow-x-auto">
              <Table className="min-w-[44rem]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-28">Date</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Account</TableHead>
                    <TableHead className="text-right">Amount</TableHead>
                    <TableHead className="w-48" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.data.data.map((row) => {
                    const linked = accountName(row.account_id)
                    return (
                      <TableRow key={row.id}>
                        <TableCell className="text-muted-foreground whitespace-nowrap tabular-nums">
                          {formatDate(row.occurred_on, { day: 'numeric', month: 'short' })}
                        </TableCell>
                        <TableCell>
                          <div className="font-medium">
                            {row.counterparty_name ?? row.description ?? 'No description'}
                          </div>
                          {row.counterparty_name && row.description ? (
                            <p className="text-muted-foreground line-clamp-1 text-xs">
                              {row.description}
                            </p>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {linked ?? row.bank_account_name ?? 'Bank account'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Money
                            minor={
                              row.direction === BankDirection.DEBIT
                                ? -row.amount_minor
                                : row.amount_minor
                            }
                            currency={row.currency_code}
                            signed
                            colored
                          />
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <RowActions
                              row={row}
                              pending={review.isPending}
                              onAccept={() => setAccepting(row)}
                              onSkip={() => review.mutate({ row, action: 'skip' })}
                              onReopen={() => review.mutate({ row, action: 'reopen' })}
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
          </Card>

          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
            noun="transaction"
          />
        </>
      )}

      <AcceptDialog row={accepting} onOpenChange={(open) => !open && setAccepting(null)} />
    </>
  )
}

/** What can be done with a row, which depends on where it is in review. */
function RowActions({
  row,
  pending,
  onAccept,
  onSkip,
  onReopen,
}: {
  row: BankTransactionPublic
  pending: boolean
  onAccept: () => void
  onSkip: () => void
  onReopen: () => void
}) {
  if (row.review_status === BankReviewStatus.ACCEPTED) {
    return <span className="text-muted-foreground text-sm">In your ledger</span>
  }
  if (row.review_status === BankReviewStatus.SKIPPED) {
    return (
      <Button variant="ghost" size="sm" onClick={onReopen} disabled={pending}>
        Put back
      </Button>
    )
  }
  return (
    <>
      {row.account_id ? (
        <Button size="sm" onClick={onAccept}>
          Accept
        </Button>
      ) : (
        // Accepting writes into the linked account, so there must be one.
        <Button size="sm" variant="outline" asChild>
          <Link to="/settings/bank">Link account</Link>
        </Button>
      )}
      <Button variant="ghost" size="sm" onClick={onSkip} disabled={pending}>
        Skip
      </Button>
    </>
  )
}
