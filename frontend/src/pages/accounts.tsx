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
import { CopyButton } from '@/components/copy-button'
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
import { formatIban } from '@/lib/iban'
import { ACCOUNT_TYPE_LABELS } from '@/lib/labels'
import { formatDate } from '@/lib/month'

const PAGE_SIZE = 25

/**
 * How the page groups accounts.
 *
 * Each section holds one kind of money, so no column mixes two of them. Cash
 * in hand is not in any bank, a credit card is what is owed rather than what
 * is held, and a brokerage balance is cash handed to a broker that net worth
 * counts through the holdings instead. A section with no accounts is left out.
 *
 * A section also drops the columns it has nothing to say in: the type when it
 * holds a single type, and the IBAN when its accounts never have one.
 *
 * The order runs from the money a bank holds to the money in a pocket.
 */
const SECTIONS: {
  title: string
  description?: string
  types: AccountType[]
  hideType?: boolean
  hideIban?: boolean
}[] = [
  {
    title: 'Banking',
    description: 'What a bank holds for you, ready to spend or put aside.',
    types: [AccountType.CURRENT, AccountType.SAVINGS],
  },
  {
    title: 'Credit cards',
    description: 'What you owe the card so far. A balance here counts against the total.',
    types: [AccountType.CREDIT_CARD],
    hideIban: true,
  },
  {
    title: 'Brokerage',
    description:
      'The cash sitting with each broker: transferred in and not yet spent, plus what sales have returned. Buying takes cash out of it, so this and your holdings never describe the same money.',
    types: [AccountType.BROKERAGE],
  },
  {
    title: 'Cash',
    description: 'What you carry, not what a bank holds for you.',
    types: [AccountType.CASH],
    hideType: true,
    hideIban: true,
  },
]

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
   * Written once and called for every section, because the page groups
   * accounts by the kind of money they hold, even though the total counts
   * all of them.
   *
   * The columns are laid out at fixed widths, with one empty column taking up
   * the slack in the middle. A section that drops the type or the IBAN then
   * widens that gap instead of shifting everything along it, so the headings
   * of every table on the page still line up with each other.
   */
  const accountTable = (
    rows: NonNullable<typeof accounts.data>['data'],
    { hideType = false, hideIban = false } = {},
  ) => (
    <Card className="overflow-hidden py-0">
      <Table className="min-w-[62rem] table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-72">Account</TableHead>
            {hideType ? null : <TableHead className="w-36">Type</TableHead>}
            {hideIban ? null : <TableHead className="w-72">IBAN</TableHead>}
            <TableHead />
            <TableHead className="w-36">Tracking since</TableHead>
            <TableHead className="w-32 text-right">Balance</TableHead>
            <TableHead className="w-12" />
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
              {hideType ? null : (
                <TableCell className="text-muted-foreground">
                  {ACCOUNT_TYPE_LABELS[account.type] ?? account.type}
                </TableCell>
              )}
              {hideIban ? null : (
                <TableCell>
                  {account.iban ? (
                    <div className="flex items-center gap-1">
                      {/* Grouped in fours to read it, copied compact to use
                          it: a payment form takes the spaces, but not every
                          one strips them. */}
                      <span className="text-muted-foreground font-mono text-xs whitespace-nowrap">
                        {formatIban(account.iban)}
                      </span>
                      <CopyButton value={account.iban} label="IBAN" />
                    </div>
                  ) : (
                    <span className="text-muted-foreground">&mdash;</span>
                  )}
                </TableCell>
              )}
              <TableCell />
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
        <div className="space-y-6">
          {SECTIONS.map((section) => {
            const rows = accounts.data.data.filter((account) =>
              section.types.includes(account.type),
            )
            if (rows.length === 0) return null

            return (
              <section key={section.title} className="space-y-2">
                <h2 className="text-sm font-medium">{section.title}</h2>
                {section.description ? (
                  <p className="text-muted-foreground text-xs">{section.description}</p>
                ) : null}
                {accountTable(rows, { hideType: section.hideType, hideIban: section.hideIban })}
              </section>
            )
          })}

          {/* A type the sections do not name yet. Listing it here rather than
              dropping it means a new account type shows up on the page before
              anyone remembers to put it in a section. */}
          {(() => {
            const named = SECTIONS.flatMap((section) => section.types)
            const rest = accounts.data.data.filter((account) => !named.includes(account.type))
            if (rest.length === 0) return null

            return (
              <section className="space-y-2">
                <h2 className="text-sm font-medium">Other</h2>
                {accountTable(rest)}
              </section>
            )
          })()}
        </div>
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
        description="This only works while nothing else points at the account, such as transactions or recurring rules paid from it or into it. Archive it instead to keep its history."
        confirmLabel="Delete account"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}
