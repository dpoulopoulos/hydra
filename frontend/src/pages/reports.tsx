import { useQuery } from '@tanstack/react-query'
import { ChartColumnIncreasing } from 'lucide-react'
import { useState } from 'react'

import {
  CategoryDepth,
  reportsIncomeExpense,
  reportsSpendByCategory,
  reportsSpendOverTime,
  TimeGranularity,
  TransactionKind,
} from '@/api'
import { IncomeExpenseChart, SavingsTrendChart } from '@/components/charts/income-expense-chart'
import { SpendByCategoryChart } from '@/components/charts/spend-by-category-chart'
import { SpendOverTimeChart } from '@/components/charts/spend-over-time-chart'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { MonthPicker } from '@/components/month-picker'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useCurrency } from '@/hooks/use-household'
import { formatPercent } from '@/lib/money'
import { currentMonth, formatMonth, monthEnd, monthStart, shiftMonth } from '@/lib/month'

export function Component() {
  const currency = useCurrency()
  const [month, setMonth] = useState(currentMonth)
  const [depth, setDepth] = useState<CategoryDepth>(CategoryDepth.PARENT)
  const [granularity, setGranularity] = useState<TimeGranularity>(TimeGranularity.DAY)
  const [months, setMonths] = useState(6)
  // The relief rule for a low-contrast mark, and a way to read the figures
  // without relying on the chart at all.
  const [asTable, setAsTable] = useState(false)

  const byCategory = useQuery({
    queryKey: ['reports', 'spend-by-category', month, depth],
    queryFn: async () => {
      const { data, error } = await reportsSpendByCategory({
        query: { month, depth, kind: TransactionKind.EXPENSE },
      })
      if (error) throw error
      return data
    },
  })

  const overTime = useQuery({
    queryKey: ['reports', 'spend-over-time', month, granularity],
    queryFn: async () => {
      // A daily chart covers the month; a monthly one the last twelve.
      const from =
        granularity === TimeGranularity.DAY ? monthStart(month) : monthStart(shiftMonth(month, -11))
      const { data, error } = await reportsSpendOverTime({
        query: {
          date_from: from,
          date_to: monthEnd(month),
          granularity,
          kind: TransactionKind.EXPENSE,
        },
      })
      if (error) throw error
      return data
    },
  })

  const flows = useQuery({
    queryKey: ['reports', 'income-expense', month, months],
    queryFn: async () => {
      const { data, error } = await reportsIncomeExpense({
        query: { month_from: shiftMonth(month, -(months - 1)), month_to: month },
      })
      if (error) throw error
      return data
    },
  })

  return (
    <>
      <PageHeader title="Reports" description="Where the money went, and what stayed." />

      <div className="flex flex-wrap items-center justify-between gap-4">
        <MonthPicker month={month} onChange={setMonth} />
        <div className="flex items-center gap-2">
          <Label htmlFor="as-table" className="text-muted-foreground text-sm font-normal">
            Show the figures
          </Label>
          <Switch id="as-table" checked={asTable} onCheckedChange={setAsTable} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Spending by category</CardTitle>
          <CardDescription>{formatMonth(month)}, largest first.</CardDescription>
          <CardAction>
            <Select value={depth} onValueChange={(value) => setDepth(value as CategoryDepth)}>
              <SelectTrigger className="w-44" aria-label="Level of detail">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={CategoryDepth.PARENT}>Grouped</SelectItem>
                <SelectItem value={CategoryDepth.LEAF}>Every subcategory</SelectItem>
              </SelectContent>
            </Select>
          </CardAction>
        </CardHeader>
        <CardContent>
          {byCategory.isPending ? (
            <LoadingRows rows={4} />
          ) : byCategory.isError ? (
            <ErrorState error={byCategory.error} />
          ) : byCategory.data.slices.length === 0 ? (
            <EmptyState
              icon={ChartColumnIncreasing}
              title="Nothing spent this month"
              description="Record some transactions and the breakdown appears here."
            />
          ) : asTable ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Category</TableHead>
                  <TableHead className="text-right">Transactions</TableHead>
                  <TableHead className="text-right">Share</TableHead>
                  <TableHead className="text-right">Spent</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {byCategory.data.slices.map((slice) => (
                  <TableRow key={slice.category_id ?? slice.category_name}>
                    <TableCell className="font-medium">{slice.category_name}</TableCell>
                    <TableCell className="text-muted-foreground text-right tabular-nums">
                      {slice.transaction_count}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-right tabular-nums">
                      {formatPercent(slice.share)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Money minor={slice.amount_minor} currency={currency} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <SpendByCategoryChart report={byCategory.data} currency={currency} />
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Spending over time</CardTitle>
          <CardDescription>
            {granularity === TimeGranularity.DAY
              ? `Every day of ${formatMonth(month)}.`
              : 'The last twelve months.'}
          </CardDescription>
          <CardAction>
            <Select
              value={granularity}
              onValueChange={(value) => setGranularity(value as TimeGranularity)}
            >
              <SelectTrigger className="w-36" aria-label="Bucket size">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={TimeGranularity.DAY}>By day</SelectItem>
                <SelectItem value={TimeGranularity.MONTH}>By month</SelectItem>
              </SelectContent>
            </Select>
          </CardAction>
        </CardHeader>
        <CardContent>
          {overTime.isPending ? (
            <LoadingRows rows={4} />
          ) : overTime.isError ? (
            <ErrorState error={overTime.error} />
          ) : (
            <>
              <SpendOverTimeChart report={overTime.data} currency={currency} />
              <p className="text-muted-foreground mt-2 text-sm">
                <Money minor={overTime.data.total_minor} currency={currency} /> in total, averaging{' '}
                <Money minor={overTime.data.average_minor} currency={currency} /> per{' '}
                {granularity === TimeGranularity.DAY ? 'active day' : 'active month'}.
              </p>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Money in against money out</CardTitle>
          <CardDescription>Transfers between your own accounts appear in neither.</CardDescription>
          <CardAction>
            <Select value={String(months)} onValueChange={(value) => setMonths(Number(value))}>
              <SelectTrigger className="w-36" aria-label="How many months">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[3, 6, 12, 24].map((count) => (
                  <SelectItem key={count} value={String(count)}>
                    {count} months
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardAction>
        </CardHeader>
        <CardContent className="space-y-6">
          {flows.isPending ? (
            <LoadingRows rows={4} />
          ) : flows.isError ? (
            <ErrorState error={flows.error} />
          ) : (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <div>
                  <p className="text-muted-foreground text-sm">Money in</p>
                  <Money
                    minor={flows.data.total_income_minor}
                    currency={currency}
                    className="text-positive text-xl"
                  />
                </div>
                <div>
                  <p className="text-muted-foreground text-sm">Money out</p>
                  <Money
                    minor={flows.data.total_expense_minor}
                    currency={currency}
                    className="text-negative text-xl"
                  />
                </div>
                <div>
                  <p className="text-muted-foreground text-sm">Saved</p>
                  <Money
                    minor={flows.data.total_net_minor}
                    currency={currency}
                    signed
                    className="text-xl"
                  />
                </div>
              </div>

              {asTable ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Month</TableHead>
                      <TableHead className="text-right">In</TableHead>
                      <TableHead className="text-right">Out</TableHead>
                      <TableHead className="text-right">Saved</TableHead>
                      <TableHead className="text-right">Running total</TableHead>
                      <TableHead className="text-right">Rate</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {flows.data.months.map((row) => (
                      <TableRow key={row.month}>
                        <TableCell className="font-medium">{formatMonth(row.month)}</TableCell>
                        <TableCell className="text-right">
                          <Money minor={row.income_minor} currency={currency} />
                        </TableCell>
                        <TableCell className="text-right">
                          <Money minor={row.expense_minor} currency={currency} />
                        </TableCell>
                        <TableCell className="text-right">
                          <Money minor={row.net_minor} currency={currency} signed colored />
                        </TableCell>
                        <TableCell className="text-right">
                          <Money minor={row.cumulative_net_minor} currency={currency} signed />
                        </TableCell>
                        <TableCell className="text-muted-foreground text-right tabular-nums">
                          {row.savings_rate === null || row.savings_rate === undefined
                            ? '—'
                            : formatPercent(row.savings_rate)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <IncomeExpenseChart report={flows.data} currency={currency} />
              )}
            </>
          )}
        </CardContent>
      </Card>

      {flows.data && !asTable ? (
        <Card>
          <CardHeader>
            <CardTitle>What stayed</CardTitle>
            <CardDescription>The running total of money kept, on its own scale.</CardDescription>
          </CardHeader>
          <CardContent>
            <SavingsTrendChart report={flows.data} currency={currency} />
          </CardContent>
        </Card>
      ) : null}
    </>
  )
}
