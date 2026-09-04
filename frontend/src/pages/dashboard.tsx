import { useQuery } from '@tanstack/react-query'
import { ArrowRight, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'

import {
  reportsBudgetProgress,
  reportsMonthSummary,
  transactionsListTransactions,
  TransactionKind,
} from '@/api'
import { BudgetBar } from '@/components/budgets/budget-bar'
import { ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { MonthPicker } from '@/components/month-picker'
import { StatTile } from '@/components/stat-tile'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { useAuth } from '@/hooks/use-auth'
import { useCurrency } from '@/hooks/use-household'
import { currentMonth, formatDate, formatMonth } from '@/lib/month'

/** A greeting that reads naturally at the hour it is shown. */
function greeting(name: string | null | undefined): string {
  const hour = new Date().getHours()
  const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const first = name?.trim().split(/\s+/)[0]
  return first ? `${part}, ${first}` : part
}

export function Component() {
  const currency = useCurrency()
  const { user } = useAuth()
  const [month, setMonth] = useState(currentMonth)

  // The summary is one request on purpose, and it also brings any recurring
  // transactions that have fallen due up to date.
  const summary = useQuery({
    queryKey: ['reports', 'summary', month],
    queryFn: async () => {
      const { data, error } = await reportsMonthSummary({ query: { month } })
      if (error) throw error
      return data
    },
  })

  const budgets = useQuery({
    queryKey: ['reports', 'budget-progress', month],
    queryFn: async () => {
      const { data, error } = await reportsBudgetProgress({ query: { month } })
      if (error) throw error
      return data
    },
  })

  const recent = useQuery({
    queryKey: ['transactions', 'recent'],
    queryFn: async () => {
      const { data, error } = await transactionsListTransactions({ query: { limit: 6 } })
      if (error) throw error
      return data
    },
  })

  const overBudget = (budgets.data?.rows ?? []).filter((row) => row.is_over_budget)

  return (
    <>
      <PageHeader
        title={greeting(user?.full_name)}
        description={`How ${formatMonth(month)} is going.`}
      >
        <Button asChild>
          <Link to="/transactions">Record a transaction</Link>
        </Button>
      </PageHeader>

      <MonthPicker month={month} onChange={setMonth} />

      {summary.isPending ? (
        <LoadingRows rows={2} />
      ) : summary.isError ? (
        <ErrorState error={summary.error} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Money in"
              minor={summary.data.income_minor}
              currency={currency}
              tone="positive"
            />
            <StatTile
              label="Money out"
              minor={summary.data.expense_minor}
              currency={currency}
              tone="negative"
            />
            <StatTile
              label="Saved"
              minor={summary.data.net_minor}
              currency={currency}
              signed
              tone="auto"
              hint={`${summary.data.transaction_count} transactions this month`}
            />
            <StatTile
              label="Net worth"
              minor={summary.data.net_worth_minor}
              currency={currency}
              hint="Across every account you have not archived"
            />
          </div>

          {overBudget.length > 0 ? (
            <Alert variant="destructive">
              <TriangleAlert className="size-4" />
              <AlertTitle>
                {overBudget.length === 1
                  ? `${overBudget[0].category_name} is over its limit`
                  : `${overBudget.length} categories are over their limit`}
              </AlertTitle>
              <AlertDescription>
                {/* The single case is already named in the title, so only a
                    list of several adds anything. */}
                {overBudget.length === 1
                  ? `Adjust the limit, or rein in the spending, before ${formatMonth(month)} is out.`
                  : `${overBudget.map((row) => row.category_name).join(', ')}.`}
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Biggest categories</CardTitle>
                <CardDescription>Where most of the money went.</CardDescription>
                <CardAction>
                  <Button variant="ghost" size="sm" asChild>
                    <Link to="/reports">
                      All reports
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                </CardAction>
              </CardHeader>
              <CardContent>
                {summary.data.top_categories.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    Nothing spent yet in {formatMonth(month)}.
                  </p>
                ) : (
                  <ul className="space-y-3">
                    {summary.data.top_categories.map((slice) => (
                      <li key={slice.category_id ?? slice.category_name} className="space-y-1">
                        <div className="flex items-baseline justify-between gap-3 text-sm">
                          <span className="font-medium">{slice.category_name}</span>
                          <Money minor={slice.amount_minor} currency={currency} />
                        </div>
                        <div className="bg-muted h-1.5 overflow-hidden rounded-full">
                          <div
                            className="bg-primary h-full rounded-full"
                            style={{ width: `${Math.round(slice.share * 100)}%` }}
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Budgets</CardTitle>
                <CardDescription>How much of each limit is used.</CardDescription>
                <CardAction>
                  <Button variant="ghost" size="sm" asChild>
                    <Link to="/budgets">
                      Manage
                      <ArrowRight className="size-4" />
                    </Link>
                  </Button>
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                {budgets.isPending ? (
                  <LoadingRows rows={3} />
                ) : budgets.data && budgets.data.rows.length > 0 ? (
                  budgets.data.rows
                    .slice(0, 4)
                    .map((row) => <BudgetBar key={row.budget_id} row={row} currency={currency} />)
                ) : (
                  <div className="space-y-3">
                    <p className="text-muted-foreground text-sm">
                      No limits set for {formatMonth(month)}.
                    </p>
                    <Button variant="outline" size="sm" asChild>
                      <Link to="/budgets">Set budgets</Link>
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Latest activity</CardTitle>
              <CardDescription>The most recent six, across every account.</CardDescription>
              <CardAction>
                <Button variant="ghost" size="sm" asChild>
                  <Link to="/transactions">
                    All transactions
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
              </CardAction>
            </CardHeader>
            <CardContent>
              {recent.isPending ? (
                <LoadingRows rows={3} />
              ) : recent.data && recent.data.count > 0 ? (
                <ul className="divide-y text-sm">
                  {recent.data.data.map((transaction) => {
                    const isTransfer = transaction.kind === TransactionKind.TRANSFER
                    const isIncome = transaction.kind === TransactionKind.INCOME

                    return (
                      <li
                        key={transaction.id}
                        className="flex items-center justify-between gap-3 py-2"
                      >
                        <span className="text-muted-foreground w-20 tabular-nums">
                          {formatDate(transaction.occurred_on, { day: 'numeric', month: 'short' })}
                        </span>
                        <span className="flex-1 truncate font-medium">
                          {transaction.merchant ?? (isTransfer ? 'Transfer' : 'No description')}
                        </span>
                        <Money
                          minor={isIncome ? transaction.amount_minor : -transaction.amount_minor}
                          currency={currency}
                          signed={!isTransfer}
                          colored={!isTransfer}
                          className={isTransfer ? 'text-muted-foreground' : undefined}
                        />
                      </li>
                    )
                  })}
                </ul>
              ) : (
                <div className="space-y-3">
                  <p className="text-muted-foreground text-sm">Nothing recorded yet.</p>
                  <Button size="sm" asChild>
                    <Link to="/transactions">Record your first transaction</Link>
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </>
  )
}
