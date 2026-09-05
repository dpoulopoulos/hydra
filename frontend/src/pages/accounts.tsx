import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, MoreHorizontal, Pencil, Trash2, Wallet } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  AccountType,
  accountsDeleteAccount,
  accountsListAccounts,
  accountsUpdateAccount,
  type AccountPublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { Pagination } from '@/components/pagination'
import { AccountDialog } from '@/components/accounts/account-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCurrency } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { ACCOUNT_TYPE_LABELS } from '@/lib/labels'
import { formatDate } from '@/lib/month'

const PAGE_SIZE = 25

export function Component() {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const [includeArchived, setIncludeArchived] = useState(false)
  const [page, setPage] = useState(0)
  const [editing, setEditing] = useState<AccountPublic | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<AccountPublic | null>(null)

  const accounts = useQuery({
    queryKey: ['accounts', { includeArchived, page }],
    queryFn: async () => {
      const { data, error } = await accountsListAccounts({
        query: { include_archived: includeArchived, skip: page * PAGE_SIZE, limit: PAGE_SIZE },
      })
      if (error) throw error
      return data
    },
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['accounts'] })
    // Balances feed the dashboard and reports too.
    void queryClient.invalidateQueries({ queryKey: ['reports'] })
  }

  const setArchived = useMutation({
    mutationFn: async ({ account, archived }: { account: AccountPublic; archived: boolean }) => {
      const { error } = await accountsUpdateAccount({
        path: { account_id: account.id },
        body: { is_archived: archived },
      })
      if (error) throw error
      return { account, archived }
    },
    onSuccess: ({ account, archived }) => {
      invalidate()
      toast.success(archived ? `${account.name} archived` : `${account.name} restored`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const remove = useMutation({
    mutationFn: async (account: AccountPublic) => {
      const { error } = await accountsDeleteAccount({ path: { account_id: account.id } })
      if (error) throw error
      return account
    },
    onSuccess: (account) => {
      invalidate()
      setDeleting(null)
      toast.success(`${account.name} deleted`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  /**
   * One table of accounts.
   *
   * Written once and called twice, because the page shows banking and
   * brokerage separately: they hold different kinds of money, even though net
   * worth counts both.
   */
  const accountTable = (rows: NonNullable<typeof accounts.data>['data']) => (
    <Card className="overflow-hidden py-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Account</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Tracking since</TableHead>
            <TableHead className="text-right">Balance</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((account) => (
            <TableRow key={account.id} className={account.archived_at ? 'opacity-60' : undefined}>
              <TableCell>
                <div className="flex items-center gap-2 font-medium">
                  {account.name}
                  {account.archived_at ? <Badge variant="secondary">Archived</Badge> : null}
                </div>
                {account.institution ? (
                  <p className="text-muted-foreground text-xs">{account.institution}</p>
                ) : null}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {ACCOUNT_TYPE_LABELS[account.type] ?? account.type}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {formatDate(account.opening_balance_date)}
              </TableCell>
              <TableCell className="text-right">
                <Money
                  minor={account.current_balance_minor ?? 0}
                  currency={account.currency_code}
                  colored={(account.current_balance_minor ?? 0) < 0}
                />
              </TableCell>
              <TableCell>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={`Manage ${account.name}`}>
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => setEditing(account)}>
                      <Pencil className="size-4" />
                      Edit
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() =>
                        setArchived.mutate({
                          account,
                          archived: account.archived_at === null,
                        })
                      }
                    >
                      {account.archived_at ? (
                        <>
                          <ArchiveRestore className="size-4" />
                          Restore
                        </>
                      ) : (
                        <>
                          <Archive className="size-4" />
                          Archive
                        </>
                      )}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onClick={() => setDeleting(account)}>
                      <Trash2 className="size-4" />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Card>
  )

  return (
    <>
      <PageHeader title="Accounts" description="Every place your household keeps money.">
        <div className="flex items-center gap-2">
          <Label htmlFor="archived" className="text-muted-foreground text-sm font-normal">
            Show archived
          </Label>
          <Switch
            id="archived"
            checked={includeArchived}
            onCheckedChange={(next) => {
              setIncludeArchived(next)
              setPage(0)
            }}
          />
        </div>
        <Button onClick={() => setCreating(true)}>Add account</Button>
      </PageHeader>

      {accounts.data && accounts.data.count > 0 ? (
        <Card>
          <CardHeader>
            {/* Not called net worth: net worth also counts what the holdings
                are worth, and that lives on the dashboard. This is the cash
                side alone, brokerage cash included. */}
            <CardTitle>Total balance</CardTitle>
            <CardDescription>
              Across {accounts.data.count} {accounts.data.count === 1 ? 'account' : 'accounts'}
            </CardDescription>
            <CardAction>
              <Money
                minor={accounts.data.total_balance_minor ?? 0}
                currency={currency}
                className="text-2xl"
              />
            </CardAction>
          </CardHeader>
        </Card>
      ) : null}

      {accounts.isPending ? (
        <LoadingRows />
      ) : accounts.isError ? (
        <ErrorState error={accounts.error} />
      ) : accounts.data.count === 0 ? (
        <EmptyState
          icon={Wallet}
          title="No accounts yet"
          description="Add the accounts you use, with the balance each one holds today. Everything else builds on them."
        >
          <Button onClick={() => setCreating(true)}>Add your first account</Button>
        </EmptyState>
      ) : (
        (() => {
          // Brokerage accounts are listed apart. Their balance is cash handed
          // to a broker rather than money to spend, and net worth counts the
          // holdings instead of it, so mixing them into one list would invite
          // adding up a column that is not meant to be added up.
          const brokerage = accounts.data.data.filter(
            (account) => account.type === AccountType.BROKERAGE,
          )
          const banking = accounts.data.data.filter(
            (account) => account.type !== AccountType.BROKERAGE,
          )

          if (brokerage.length === 0) return accountTable(banking)

          return (
            <div className="space-y-6">
              {banking.length > 0 ? (
                <section className="space-y-2">
                  <h2 className="text-sm font-medium">Banking</h2>
                  {accountTable(banking)}
                </section>
              ) : null}
              <section className="space-y-2">
                <h2 className="text-sm font-medium">Brokerage</h2>
                <p className="text-muted-foreground text-xs">
                  The cash sitting with each broker: transferred in and not yet spent, plus what
                  sales have returned. Buying takes cash out of it, so this and your holdings never
                  describe the same money.
                </p>
                {accountTable(brokerage)}
              </section>
            </div>
          )
        })()
      )}

      {accounts.data && accounts.data.count > 0 ? (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={accounts.data.count}
          onPageChange={setPage}
          noun="account"
        />
      ) : null}

      <AccountDialog
        open={creating || editing !== null}
        account={editing}
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
        title={`Delete ${deleting?.name}?`}
        description="This only works while the account has no transactions. Archive it instead to keep its history."
        confirmLabel="Delete account"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}
