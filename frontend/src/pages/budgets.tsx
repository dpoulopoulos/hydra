import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, MoreHorizontal, Pencil, Plus, Target, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { budgetsDeleteBudget, reportsBudgetProgress, type BudgetProgressRow } from '@/api'
import { BudgetBar } from '@/components/budgets/budget-bar'
import { BudgetEditor } from '@/components/budgets/budget-editor'
import { CopyMonthDialog } from '@/components/budgets/copy-month-dialog'
import { SingleBudgetDialog } from '@/components/budgets/single-budget-dialog'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { MonthPicker } from '@/components/month-picker'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useCurrency } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { currentMonth } from '@/lib/month'

export function Component() {
  const currency = useCurrency()
  const [month, setMonth] = useState(currentMonth)
  const [editing, setEditing] = useState(false)
  const [copying, setCopying] = useState(false)
  const [single, setSingle] = useState<{ row: BudgetProgressRow | null } | null>(null)
  const [removing, setRemoving] = useState<BudgetProgressRow | null>(null)
  const queryClient = useQueryClient()

  const progress = useQuery({
    queryKey: ['reports', 'budget-progress', month],
    queryFn: async () => {
      const { data, error } = await reportsBudgetProgress({ query: { month } })
      if (error) throw error
      return data
    },
  })

  const remove = useMutation({
    mutationFn: async (row: BudgetProgressRow) => {
      const { error } = await budgetsDeleteBudget({ path: { budget_id: row.budget_id } })
      if (error) throw error
      return row
    },
    onSuccess: (row) => {
      void queryClient.invalidateQueries({ queryKey: ['budgets'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      setRemoving(null)
      toast.success(`${row.category_name} is no longer budgeted`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <>
      <PageHeader
        title="Budgets"
        description="A limit per category per month. Nothing carries over."
      >
        <Button variant="outline" onClick={() => setCopying(true)}>
          <Copy className="size-4" />
          Copy a month
        </Button>
        <Button variant="outline" onClick={() => setSingle({ row: null })}>
          <Plus className="size-4" />
          One category
        </Button>
        <Button onClick={() => setEditing(true)}>Set budgets</Button>
      </PageHeader>

      <MonthPicker month={month} onChange={setMonth} />

      {progress.isPending ? (
        <LoadingRows rows={5} />
      ) : progress.isError ? (
        <ErrorState error={progress.error} />
      ) : progress.data.rows.length === 0 ? (
        <EmptyState
          icon={Target}
          title="No budgets this month"
          description="Set a limit on the categories you want to keep an eye on. A limit on a parent covers everything under it."
        >
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setSingle({ row: null })}>
              <Plus className="size-4" />
              One category
            </Button>
            <Button onClick={() => setEditing(true)}>Set budgets</Button>
            <Button variant="outline" onClick={() => setCopying(true)}>
              Copy an earlier month
            </Button>
          </div>
        </EmptyState>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardHeader className="gap-1">
                <CardDescription>Budgeted</CardDescription>
                <CardTitle className="text-2xl">
                  <Money minor={progress.data.total_limit_minor} currency={currency} />
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="gap-1">
                <CardDescription>Spent against it</CardDescription>
                <CardTitle className="text-2xl">
                  <Money minor={progress.data.total_spent_minor} currency={currency} />
                </CardTitle>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader className="gap-1">
                <CardDescription>
                  {progress.data.total_remaining_minor < 0 ? 'Over budget' : 'Still available'}
                </CardDescription>
                <CardTitle className="text-2xl">
                  <Money
                    minor={Math.abs(progress.data.total_remaining_minor)}
                    currency={currency}
                    className={
                      progress.data.total_remaining_minor < 0 ? 'text-negative' : 'text-positive'
                    }
                  />
                </CardTitle>
              </CardHeader>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Where it stands</CardTitle>
              <CardDescription>Most of the limit used, first.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              {progress.data.rows.map((row) => (
                <div key={row.budget_id} className="flex items-start gap-2">
                  <div className="flex-1">
                    <BudgetBar row={row} currency={currency} />
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={`Manage the limit for ${row.category_name}`}
                      >
                        <MoreHorizontal className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => setSingle({ row })}>
                        <Pencil className="size-4" />
                        Change the limit
                      </DropdownMenuItem>
                      <DropdownMenuItem variant="destructive" onClick={() => setRemoving(row)}>
                        <Trash2 className="size-4" />
                        Stop budgeting it
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              ))}
            </CardContent>
          </Card>

          {progress.data.unbudgeted_spend_minor > 0 ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Spending with no limit</CardTitle>
                <CardDescription>
                  Money that went out in categories you have not budgeted this month.
                </CardDescription>
                <CardAction>
                  <Money
                    minor={progress.data.unbudgeted_spend_minor}
                    currency={currency}
                    className="text-xl"
                  />
                </CardAction>
              </CardHeader>
            </Card>
          ) : null}
        </>
      )}

      <BudgetEditor open={editing} month={month} onOpenChange={setEditing} />
      <CopyMonthDialog open={copying} month={month} onOpenChange={setCopying} />
      <SingleBudgetDialog
        open={single !== null}
        month={month}
        row={single?.row ?? null}
        onOpenChange={(open) => !open && setSingle(null)}
      />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Stop budgeting ${removing?.category_name}?`}
        description="The limit goes; the spending stays. It will show under spending with no limit."
        confirmLabel="Remove the limit"
        pending={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing)}
      />
    </>
  )
}
