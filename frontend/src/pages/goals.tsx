import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChartColumn,
  CircleCheck,
  Flag,
  MoreHorizontal,
  Pencil,
  RotateCcw,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  goalsDeleteGoal,
  goalsGetGoalHistory,
  goalsUpdateGoal,
  type GoalAccountSummary,
  type GoalPublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { GoalBar } from '@/components/goals/goal-bar'
import { GoalDialog } from '@/components/goals/goal-dialog'
import { GoalHistoryChart } from '@/components/goals/goal-history-chart'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useGoals } from '@/hooks/use-goals'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/month'
import { cn } from '@/lib/utils'

export function Component() {
  const queryClient = useQueryClient()
  const goals = useGoals()
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<GoalPublic | null>(null)
  const [deleting, setDeleting] = useState<GoalPublic | null>(null)
  const [viewing, setViewing] = useState<GoalPublic | null>(null)

  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ['goals'] })

  const setAchieved = useMutation({
    mutationFn: async ({ goal, achieved }: { goal: GoalPublic; achieved: boolean }) => {
      const { error } = await goalsUpdateGoal({
        path: { goal_id: goal.id },
        body: { is_achieved: achieved },
      })
      if (error) throw error
      return { goal, achieved }
    },
    onSuccess: ({ goal, achieved }) => {
      invalidate()
      toast.success(achieved ? `${goal.name} marked as reached` : `${goal.name} reopened`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const remove = useMutation({
    mutationFn: async (goal: GoalPublic) => {
      const { error } = await goalsDeleteGoal({ path: { goal_id: goal.id } })
      if (error) throw error
      return goal
    },
    onSuccess: (goal) => {
      invalidate()
      // Transfers keep their place in the ledger; only the tag goes.
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      setDeleting(null)
      toast.success(`${goal.name} deleted. Its money is now unassigned.`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <>
      <PageHeader
        title="Goals"
        description="What you are saving for, and how much to put aside each month to get there."
      >
        <Button onClick={() => setCreating(true)}>Add a goal</Button>
      </PageHeader>

      {goals.isPending ? (
        <LoadingRows rows={4} />
      ) : goals.isError ? (
        <ErrorState error={goals.error} />
      ) : goals.data.count === 0 ? (
        <EmptyState
          icon={Flag}
          title="No goals yet"
          description="Add something to save for, like a new car. Link it to a savings account, then tag the transfers you make into that account with the goal."
        >
          <Button onClick={() => setCreating(true)}>Add your first goal</Button>
        </EmptyState>
      ) : (
        <div className="space-y-6">
          {goals.data.accounts.map((account) => (
            <AccountCard
              key={account.account_id}
              account={account}
              goals={goals.data.data.filter((goal) => goal.account_id === account.account_id)}
              onEdit={setEditing}
              onHistory={setViewing}
              onDelete={setDeleting}
              onAchieved={(goal, achieved) => setAchieved.mutate({ goal, achieved })}
            />
          ))}
        </div>
      )}

      <GoalDialog
        open={creating || editing !== null}
        goal={editing}
        onOpenChange={(open) => {
          if (!open) {
            setCreating(false)
            setEditing(null)
          }
        }}
      />

      <HistoryDialog goal={viewing} onOpenChange={(open) => !open && setViewing(null)} />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name ?? 'this goal'}?`}
        description="The transfers tagged with it stay in your ledger. Their money becomes unassigned in the savings account."
        confirmLabel="Delete goal"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}

function AccountCard({
  account,
  goals,
  onEdit,
  onHistory,
  onDelete,
  onAchieved,
}: {
  account: GoalAccountSummary
  goals: GoalPublic[]
  onEdit: (goal: GoalPublic) => void
  onHistory: (goal: GoalPublic) => void
  onDelete: (goal: GoalPublic) => void
  onAchieved: (goal: GoalPublic, achieved: boolean) => void
}) {
  const currency = account.currency_code

  return (
    <Card>
      <CardHeader>
        <CardTitle>{account.account_name}</CardTitle>
        <CardDescription>
          {/* The goals and what is left over always add up to the balance. */}
          <Money minor={account.assigned_minor} currency={currency} /> in goals,{' '}
          <Money
            minor={account.unassigned_minor}
            currency={currency}
            className={account.unassigned_minor < 0 ? 'text-negative' : undefined}
          />{' '}
          unassigned
        </CardDescription>
        <CardAction>
          <Money minor={account.balance_minor} currency={currency} className="text-xl" />
        </CardAction>
      </CardHeader>
      <CardContent>
        <ul className="divide-y">
          {goals.map((goal) => (
            <li
              key={goal.id}
              className={cn(
                'space-y-2 py-4 first:pt-0 last:pb-0',
                goal.achieved_at && 'opacity-60',
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2 font-medium">
                    {goal.name}
                    <GoalStatus goal={goal} />
                  </div>
                  <Pace goal={goal} />
                </div>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" aria-label={`Manage ${goal.name}`}>
                      <MoreHorizontal className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => onHistory(goal)}>
                      <ChartColumn className="size-4" />
                      Monthly savings
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => onEdit(goal)}>
                      <Pencil className="size-4" />
                      Edit
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => onAchieved(goal, !goal.achieved_at)}>
                      {goal.achieved_at ? (
                        <>
                          <RotateCcw className="size-4" />
                          Reopen
                        </>
                      ) : (
                        <>
                          <CircleCheck className="size-4" />
                          Mark as reached
                        </>
                      )}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem variant="destructive" onClick={() => onDelete(goal)}>
                      <Trash2 className="size-4" />
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
              <GoalBar goal={goal} />
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

function GoalStatus({ goal }: { goal: GoalPublic }) {
  if (goal.achieved_at) return <Badge variant="secondary">Reached</Badge>
  if (goal.remaining_minor === 0) return <Badge>Fully saved</Badge>
  if (goal.on_track === true) return <Badge variant="outline">On track</Badge>
  if (goal.on_track === false) return <Badge variant="destructive">Behind</Badge>
  return null
}

/** One line on what the goal needs from here, in the terms a person plans in. */
function Pace({ goal }: { goal: GoalPublic }) {
  const currency = goal.currency_code

  if (goal.achieved_at || goal.remaining_minor === 0 || !goal.target_date) {
    return goal.target_date ? (
      <p className="text-muted-foreground text-xs">By {formatDate(goal.target_date)}</p>
    ) : null
  }

  if (goal.months_left === 0) {
    return (
      <p className="text-negative text-xs">
        The date has passed. <Money minor={goal.remaining_minor} currency={currency} /> still to go.
      </p>
    )
  }

  return (
    <p className="text-muted-foreground text-xs">
      Save <Money minor={goal.needed_per_month_minor ?? 0} currency={currency} /> a month to reach
      it by {formatDate(goal.target_date)}. Lately:{' '}
      <Money minor={goal.average_monthly_minor} currency={currency} /> a month.
    </p>
  )
}

function HistoryDialog({
  goal,
  onOpenChange,
}: {
  goal: GoalPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const history = useQuery({
    queryKey: ['goals', goal?.id, 'history'],
    queryFn: async () => {
      const { data, error } = await goalsGetGoalHistory({ path: { goal_id: goal!.id } })
      if (error) throw error
      return data
    },
    enabled: goal !== null,
  })

  return (
    <Dialog open={goal !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{goal?.name}: monthly savings</DialogTitle>
          <DialogDescription>
            What went into the goal each month over the last year, less what came out.
          </DialogDescription>
        </DialogHeader>
        {history.isPending ? (
          <LoadingRows rows={3} />
        ) : history.isError ? (
          <ErrorState error={history.error} />
        ) : goal ? (
          <GoalHistoryChart
            history={history.data}
            currency={goal.currency_code}
            neededPerMonth={goal.achieved_at ? null : goal.needed_per_month_minor}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
