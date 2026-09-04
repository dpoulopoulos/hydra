import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { budgetsBulkUpsertBudgets, budgetsListBudgets, CategoryKind } from '@/api'
import { FormError } from '@/components/form-field'
import { MoneyInput } from '@/components/money-input'
import { SubmitButton } from '@/components/submit-button'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useCategoryTree } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { toMajor, toMinor } from '@/lib/money'
import { formatMonth } from '@/lib/month'

/**
 * Set a whole month of limits at once.
 *
 * The API takes the month as one set, and a category left out has its limit
 * removed, so this edits every category on one screen rather than opening a
 * dialog per category. Only expense categories appear: a budget is a spending
 * limit, so a limit on Salary would mean nothing.
 */
export function BudgetEditor({
  open,
  month,
  onOpenChange,
}: {
  open: boolean
  month: string
  onOpenChange: (open: boolean) => void
}) {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const { data: tree } = useCategoryTree({ kind: CategoryKind.EXPENSE })
  // Edits are held separately from the saved figures, so the field values can
  // be derived rather than copied into state by an effect, which would set
  // state during render and cascade.
  const [edits, setEdits] = useState<Record<string, string>>({})

  const existing = useQuery({
    queryKey: ['budgets', month],
    queryFn: async () => {
      const { data, error } = await budgetsListBudgets({ query: { month } })
      if (error) throw error
      return data
    },
    enabled: open,
  })

  const saved = useMemo(
    () =>
      Object.fromEntries(
        (existing.data?.data ?? []).map((budget) => [
          budget.category_id,
          String(toMajor(budget.limit_minor, currency)),
        ]),
      ),
    [existing.data, currency],
  )

  /** What a field shows: the edit if there is one, otherwise the saved limit. */
  const valueFor = (categoryId: string) => edits[categoryId] ?? saved[categoryId] ?? ''

  const limits = { ...saved, ...edits }

  const save = useMutation({
    mutationFn: async () => {
      const entries = Object.entries(limits)
        .map(([category_id, value]) => ({
          category_id,
          limit_minor: toMinor(Number(value.replace(',', '.')), currency),
        }))
        // A blank or zero field means "not budgeted", so it is left out of the
        // set rather than sent as a limit of nothing.
        .filter((entry) => Number.isFinite(entry.limit_minor) && entry.limit_minor > 0)

      const { error } = await budgetsBulkUpsertBudgets({ body: { month, entries } })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['budgets'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(`Budgets set for ${formatMonth(month)}`)
      onOpenChange(false)
    },
  })

  const parents = tree?.data ?? []

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setEdits({})
        onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Budgets for {formatMonth(month)}</DialogTitle>
          <DialogDescription>
            A limit on a parent covers everything under it, so budget the parent or its
            subcategories, not both. Leave a field empty to stop budgeting it.
          </DialogDescription>
        </DialogHeader>

        <FormError message={save.isError ? errorMessage(save.error) : null} />

        <ScrollArea className="-mx-2 max-h-[50vh] px-2">
          <div className="space-y-4">
            {parents.map((parent) => (
              <div key={parent.id} className="space-y-2">
                <div className="flex items-center gap-3">
                  <Label htmlFor={`limit-${parent.id}`} className="flex-1 font-medium">
                    {parent.name}
                  </Label>
                  <MoneyInput
                    id={`limit-${parent.id}`}
                    currency={currency}
                    className="w-40"
                    value={valueFor(parent.id)}
                    onChange={(event) =>
                      setEdits((current) => ({ ...current, [parent.id]: event.target.value }))
                    }
                  />
                </div>
                {(parent.children ?? []).map((child) => (
                  <div key={child.id} className="flex items-center gap-3 pl-4">
                    <Label
                      htmlFor={`limit-${child.id}`}
                      className="text-muted-foreground flex-1 font-normal"
                    >
                      {child.name}
                    </Label>
                    <MoneyInput
                      id={`limit-${child.id}`}
                      currency={currency}
                      className="w-40"
                      value={valueFor(child.id)}
                      onChange={(event) =>
                        setEdits((current) => ({ ...current, [child.id]: event.target.value }))
                      }
                    />
                  </div>
                ))}
              </div>
            ))}
          </div>
        </ScrollArea>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton pending={save.isPending} onClick={() => save.mutate()} type="button">
            Save budgets
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
