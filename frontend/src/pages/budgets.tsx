import { useQuery } from '@tanstack/react-query'
import { Copy, Target } from 'lucide-react'
import { useState } from 'react'

import { reportsBudgetProgress } from '@/api'
import { BudgetBar } from '@/components/budgets/budget-bar'
import { BudgetEditor } from '@/components/budgets/budget-editor'
import { CopyMonthDialog } from '@/components/budgets/copy-month-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { MonthPicker } from '@/components/month-picker'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useCurrency } from '@/hooks/use-household'
import { currentMonth } from '@/lib/month'

export function Component() {
  const currency = useCurrency()
  const [month, setMonth] = useState(currentMonth)
  const [editing, setEditing] = useState(false)
  const [copying, setCopying] = useState(false)

  const progress = useQuery({
    queryKey: ['reports', 'budget-progress', month],
    queryFn: async () => {
      const { data, error } = await reportsBudgetProgress({ query: { month } })
      if (error) throw error
      return data
    },
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
                <BudgetBar key={row.budget_id} row={row} currency={currency} />
              ))}
            </CardContent>
          </Card>

          {progress.data.unbudgeted_spend_minor > 0 ? (
            <Card>
              <CardHeader className="flex-row items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-base">Spending with no limit</CardTitle>
                  <CardDescription>
                    Money that went out in categories you have not budgeted this month.
                  </CardDescription>
                </div>
                <Money
                  minor={progress.data.unbudgeted_spend_minor}
                  currency={currency}
                  className="text-xl"
                />
              </CardHeader>
            </Card>
          ) : null}
        </>
      )}

      <BudgetEditor open={editing} month={month} onOpenChange={setEditing} />
      <CopyMonthDialog open={copying} month={month} onOpenChange={setCopying} />
    </>
  )
}
