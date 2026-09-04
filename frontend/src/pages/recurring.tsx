import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarClock, MoreHorizontal, Pause, Pencil, Play, Repeat, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import {
  recurringRulesDeleteRecurringRule,
  recurringRulesListRecurringRules,
  recurringRulesListUpcomingOccurrences,
  recurringRulesRunRecurringRules,
  recurringRulesUpdateRecurringRule,
  TransactionKind,
  type RecurringRulePublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { RuleDialog } from '@/components/recurring/rule-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
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
import { useCurrency } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { describeSchedule } from '@/lib/labels'
import { formatDate } from '@/lib/month'

export function Component() {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState<RecurringRulePublic | null>(null)
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<RecurringRulePublic | null>(null)

  const rules = useQuery({
    queryKey: ['recurring', 'rules'],
    queryFn: async () => {
      const { data, error } = await recurringRulesListRecurringRules({ query: { limit: 200 } })
      if (error) throw error
      return data
    },
  })

  const upcoming = useQuery({
    queryKey: ['recurring', 'upcoming'],
    queryFn: async () => {
      const { data, error } = await recurringRulesListUpcomingOccurrences({})
      if (error) throw error
      return data
    },
  })

  const { data: accounts } = useAccounts({ includeArchived: true })
  const accountNames = useMemo(
    () => new Map((accounts?.data ?? []).map((account) => [account.id, account.name])),
    [accounts],
  )

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['recurring'] })
    void queryClient.invalidateQueries({ queryKey: ['transactions'] })
    void queryClient.invalidateQueries({ queryKey: ['accounts'] })
    void queryClient.invalidateQueries({ queryKey: ['reports'] })
  }

  const run = useMutation({
    mutationFn: async () => {
      const { data, error } = await recurringRulesRunRecurringRules({})
      if (error) throw error
      return data
    },
    onSuccess: (result) => {
      invalidate()
      const created = result?.created_count ?? 0
      toast.success(
        created === 0
          ? 'Nothing was due'
          : `Recorded ${created} ${created === 1 ? 'transaction' : 'transactions'}`,
      )
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const setActive = useMutation({
    mutationFn: async ({ rule, active }: { rule: RecurringRulePublic; active: boolean }) => {
      const { error } = await recurringRulesUpdateRecurringRule({
        path: { rule_id: rule.id },
        body: { is_active: active },
      })
      if (error) throw error
      return { rule, active }
    },
    onSuccess: ({ rule, active }) => {
      invalidate()
      toast.success(active ? `${rule.name} resumed` : `${rule.name} paused`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const remove = useMutation({
    mutationFn: async (rule: RecurringRulePublic) => {
      const { error } = await recurringRulesDeleteRecurringRule({ path: { rule_id: rule.id } })
      if (error) throw error
      return rule
    },
    onSuccess: (rule) => {
      invalidate()
      setDeleting(null)
      toast.success(`${rule.name} deleted. Its transactions are kept.`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <>
      <PageHeader
        title="Recurring"
        description="Rent, subscriptions, standing transfers. Recorded as each one falls due."
      >
        <Button variant="outline" onClick={() => run.mutate()} disabled={run.isPending}>
          <CalendarClock className="size-4" />
          Catch up now
        </Button>
        <Button onClick={() => setCreating(true)}>Add a rule</Button>
      </PageHeader>

      {rules.isPending ? (
        <LoadingRows rows={4} />
      ) : rules.isError ? (
        <ErrorState error={rules.error} />
      ) : rules.data.count === 0 ? (
        <EmptyState
          icon={Repeat}
          title="No recurring rules"
          description="Add the payments that repeat, and hydra records each one instead of you retyping it every month."
        >
          <Button onClick={() => setCreating(true)}>Add your first rule</Button>
        </EmptyState>
      ) : (
        <Card className="overflow-hidden py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Rule</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Account</TableHead>
                <TableHead>Next</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rules.data.data.map((rule) => (
                <TableRow key={rule.id} className={rule.is_active ? undefined : 'opacity-60'}>
                  <TableCell>
                    <div className="flex items-center gap-2 font-medium">
                      {rule.name}
                      {!rule.is_active ? <Badge variant="secondary">Paused</Badge> : null}
                      {rule.kind === TransactionKind.INCOME ? (
                        <Badge variant="outline">Income</Badge>
                      ) : rule.kind === TransactionKind.TRANSFER ? (
                        <Badge variant="outline">Transfer</Badge>
                      ) : null}
                    </div>
                    {rule.merchant ? (
                      <p className="text-muted-foreground text-xs">{rule.merchant}</p>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {describeSchedule(rule.frequency, rule.interval, rule.day_of_month)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {accountNames.get(rule.account_id) ?? 'Unknown'}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {rule.next_occurrence_on ? formatDate(rule.next_occurrence_on) : 'Finished'}
                  </TableCell>
                  <TableCell className="text-right">
                    <Money minor={rule.amount_minor} currency={currency} />
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label={`Manage ${rule.name}`}>
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => setEditing(rule)}>
                          <Pencil className="size-4" />
                          Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          onClick={() => setActive.mutate({ rule, active: !rule.is_active })}
                        >
                          {rule.is_active ? (
                            <>
                              <Pause className="size-4" />
                              Pause
                            </>
                          ) : (
                            <>
                              <Play className="size-4" />
                              Resume
                            </>
                          )}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={() => setDeleting(rule)}>
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
      )}

      {upcoming.data && upcoming.data.count > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Still to come</CardTitle>
            <CardDescription>
              The next two months, projected. Nothing here is recorded yet.
            </CardDescription>
            <CardAction>
              <Money
                minor={upcoming.data.total_minor ?? 0}
                currency={currency}
                className="text-xl whitespace-nowrap"
              />
            </CardAction>
          </CardHeader>
          <CardContent>
            <ul className="divide-y text-sm">
              {upcoming.data.data.map((occurrence, index) => (
                <li
                  key={`${occurrence.rule_id}-${occurrence.occurs_on}-${index}`}
                  className="flex items-center justify-between gap-3 py-2"
                >
                  <span className="text-muted-foreground w-28 tabular-nums">
                    {formatDate(occurrence.occurs_on, { day: 'numeric', month: 'short' })}
                  </span>
                  <span className="flex-1 font-medium">{occurrence.name}</span>
                  <Money
                    minor={
                      occurrence.kind === TransactionKind.INCOME
                        ? occurrence.amount_minor
                        : -occurrence.amount_minor
                    }
                    currency={currency}
                    signed={occurrence.kind !== TransactionKind.TRANSFER}
                    colored={occurrence.kind !== TransactionKind.TRANSFER}
                  />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <RuleDialog
        open={creating || editing !== null}
        rule={editing}
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
        description="The transactions it already recorded are kept. Only the rule goes."
        confirmLabel="Delete rule"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}
