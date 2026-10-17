import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronsDownUp,
  ChevronsUpDown,
  Copy,
  MoreHorizontal,
  Pencil,
  Plus,
  Target,
  Trash2,
} from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

import {
  budgetsDeleteBudget,
  CategoryKind,
  reportsBudgetProgress,
  type BudgetProgressRow,
} from '@/api'
import { BudgetBar } from '@/components/budgets/budget-bar'
import { BudgetEditor } from '@/components/budgets/budget-editor'
import { CopyMonthDialog } from '@/components/budgets/copy-month-dialog'
import { SingleBudgetDialog } from '@/components/budgets/single-budget-dialog'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { MonthPicker } from '@/components/month-picker'
import { OtherCurrenciesNote } from '@/components/other-currencies-note'
import { StatTile } from '@/components/stat-tile'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { useCategoryTree } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { groupBudgetRows, type BudgetFigures } from '@/lib/budgets'
import { currentMonth } from '@/lib/month'
import { cn } from '@/lib/utils'

export function Component() {
  const currency = useCurrency()
  const [month, setMonth] = useState(currentMonth)
  const [editing, setEditing] = useState(false)
  const [copying, setCopying] = useState(false)
  const [single, setSingle] = useState<{ row: BudgetProgressRow | null } | null>(null)
  const [removing, setRemoving] = useState<BudgetProgressRow | null>(null)
  // The parents folded shut. Kept by category, so a parent stays shut when
  // the month changes.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set())
  const queryClient = useQueryClient()

  const progress = useQuery({
    queryKey: ['reports', 'budget-progress', month],
    queryFn: async () => {
      const { data, error } = await reportsBudgetProgress({ query: { month } })
      if (error) throw error
      return data
    },
  })
  // Archived parents included, so a subcategory budgeted under one is still
  // gathered under it.
  const tree = useCategoryTree({ includeArchived: true, kind: CategoryKind.EXPENSE })
  const groups = useMemo(
    () => groupBudgetRows(progress.data?.rows ?? [], tree.data?.data ?? []),
    [progress.data, tree.data],
  )
  const parentIds = groups.flatMap((group) => (group.kind === 'parent' ? [group.categoryId] : []))
  const allCollapsed = parentIds.length > 0 && parentIds.every((id) => collapsed.has(id))

  function toggle(categoryId: string, open: boolean) {
    setCollapsed((previous) => {
      const next = new Set(previous)
      if (open) next.delete(categoryId)
      else next.add(categoryId)
      return next
    })
  }

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
      <OtherCurrenciesNote />

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
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4">
            <StatTile
              label="Budgeted"
              minor={progress.data.total_limit_minor}
              currency={currency}
            />
            <StatTile
              label="Spent against it"
              minor={progress.data.total_spent_minor}
              currency={currency}
            />
            <StatTile
              className="max-sm:col-span-2"
              label={progress.data.total_remaining_minor < 0 ? 'Over budget' : 'Still available'}
              minor={Math.abs(progress.data.total_remaining_minor)}
              currency={currency}
              tone={progress.data.total_remaining_minor < 0 ? 'negative' : 'positive'}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Where it stands</CardTitle>
              <CardDescription>Most of the limit used, first.</CardDescription>
              {parentIds.length > 0 ? (
                <CardAction>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCollapsed(allCollapsed ? new Set() : new Set(parentIds))}
                  >
                    {allCollapsed ? (
                      <ChevronsUpDown className="size-4" />
                    ) : (
                      <ChevronsDownUp className="size-4" />
                    )}
                    {allCollapsed ? 'Expand all' : 'Collapse all'}
                  </Button>
                </CardAction>
              ) : null}
            </CardHeader>
            <CardContent className="space-y-5">
              {groups.map((group) =>
                group.kind === 'row' ? (
                  <BudgetRow
                    key={group.row.budget_id}
                    row={group.row}
                    currency={currency}
                    onChange={(row) => setSingle({ row })}
                    onRemove={setRemoving}
                  />
                ) : (
                  <ParentGroup
                    key={group.categoryId}
                    total={group.total}
                    open={!collapsed.has(group.categoryId)}
                    onOpenChange={(open) => toggle(group.categoryId, open)}
                    currency={currency}
                  >
                    {group.rows.map((row) => (
                      <BudgetRow
                        key={row.budget_id}
                        row={row}
                        currency={currency}
                        onChange={(row) => setSingle({ row })}
                        onRemove={setRemoving}
                      />
                    ))}
                  </ParentGroup>
                ),
              )}
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

/**
 * A parent's bar, with its subcategories' bars under it.
 *
 * No menu: the parent has no limit of its own to change, only its
 * subcategories' limits added up. The button that folds them away sits where
 * the menu would, so its bar is as wide as theirs.
 */
function ParentGroup({
  total,
  open,
  onOpenChange,
  currency,
  children,
}: {
  total: BudgetFigures
  open: boolean
  onOpenChange: (open: boolean) => void
  currency: string
  children: ReactNode
}) {
  return (
    <Collapsible open={open} onOpenChange={onOpenChange} className="space-y-4">
      <div className="flex items-start gap-2">
        <div className="flex-1">
          <BudgetBar row={total} currency={currency} note="its subcategories added up" />
        </div>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`${open ? 'Hide' : 'Show'} the subcategories of ${total.category_name}`}
          >
            <ChevronDown className={cn('size-4 transition-transform', open && 'rotate-180')} />
          </Button>
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className="border-muted space-y-4 border-l-2 pl-4">
        {children}
      </CollapsibleContent>
    </Collapsible>
  )
}

/** One budget's bar, with the menu to change or remove its limit. */
function BudgetRow({
  row,
  currency,
  onChange,
  onRemove,
}: {
  row: BudgetProgressRow
  currency: string
  onChange: (row: BudgetProgressRow) => void
  onRemove: (row: BudgetProgressRow) => void
}) {
  return (
    <div className="flex items-start gap-2">
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
          <DropdownMenuItem onClick={() => onChange(row)}>
            <Pencil className="size-4" />
            Change the limit
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" onClick={() => onRemove(row)}>
            <Trash2 className="size-4" />
            Stop budgeting it
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
