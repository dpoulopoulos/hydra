import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  budgetsCreateBudget,
  budgetsUpdateBudget,
  CategoryKind,
  type BudgetProgressRow,
} from '@/api'
import { Field, FormError } from '@/components/form-field'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCategoryTree } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { formatMajorInput } from '@/lib/money'
import { formatMonth } from '@/lib/month'
import { optionSource } from '@/lib/option-source'

/**
 * Set or change one category's limit.
 *
 * The month editor is for going through every category at once; this is for
 * the single change, which is the more common errand.
 */
export function SingleBudgetDialog({
  open,
  month,
  row,
  onOpenChange,
}: {
  open: boolean
  month: string
  /** The budget being changed, or null when adding one. */
  row: BudgetProgressRow | null
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {/* Keyed so the form remounts per budget and takes its starting values
            from props, rather than copying them in with an effect. */}
        {open ? (
          <BudgetForm
            key={row?.budget_id ?? 'new'}
            month={month}
            row={row}
            onDone={() => onOpenChange(false)}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}

function BudgetForm({
  month,
  row,
  onDone,
}: {
  month: string
  row: BudgetProgressRow | null
  onDone: () => void
}) {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const categoriesQuery = useCategoryTree({ kind: CategoryKind.EXPENSE })
  // A picker with nothing in it says the household has no categories. When the
  // tree was refused rather than empty, the field says so instead.
  const categorySource = optionSource(categoriesQuery, 'categories')
  const [categoryId, setCategoryId] = useState(row?.category_id ?? '')
  const [limit, setLimit] = useState(row ? formatMajorInput(row.limit_minor, currency) : '')
  // What a field got wrong. Filled on a save attempt rather than while typing,
  // since a half-typed amount is not a mistake.
  const [fieldErrors, setFieldErrors] = useState<{ category?: string; limit?: string }>({})
  const isEdit = row !== null

  const save = useMutation({
    mutationFn: async (limitMinor: number) => {
      if (row) {
        const { error } = await budgetsUpdateBudget({
          path: { budget_id: row.budget_id },
          body: { limit_minor: limitMinor },
        })
        if (error) throw error
        return
      }

      const { error } = await budgetsCreateBudget({
        body: { category_id: categoryId, month, limit_minor: limitMinor },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['budgets'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(isEdit ? 'Limit changed' : 'Limit set')
      onDone()
    },
  })

  /**
   * Send the limit, unless a field cannot be read.
   *
   * The amount goes through the shared schema, which takes "1 000" and "42,50"
   * as people type them, so the only values reported back are ones nobody
   * could read as a number, and they are reported on the field that holds them
   * rather than as a complaint about the whole form.
   */
  const attemptSave = () => {
    const amount = amountSchema(currency, { allowZero: true }).safeParse(limit)
    const errors = {
      category: !isEdit && !categoryId ? 'Choose a category.' : undefined,
      limit: amount.success ? undefined : amount.error.issues[0].message,
    }

    setFieldErrors(errors)
    if (!amount.success || errors.category) return
    save.mutate(amount.data)
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>
          {isEdit ? `Limit for ${row.category_name}` : `Set a limit for ${formatMonth(month)}`}
        </DialogTitle>
        <DialogDescription>
          A limit on a parent category covers everything filed under it, so budget the parent or its
          subcategories, not both.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4">
        <FormError message={save.isError ? errorMessage(save.error) : null} />

        {!isEdit ? (
          <Field
            id="budget-category"
            label="Category"
            error={fieldErrors.category ?? categorySource.error}
          >
            {(props) => (
              <Select
                value={categoryId}
                onValueChange={(value) => {
                  setCategoryId(value)
                  setFieldErrors((current) => ({ ...current, category: undefined }))
                }}
                disabled={categorySource.unavailable}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue placeholder="Choose a category" />
                </SelectTrigger>
                <SelectContent>
                  {categorySource.options.map((parent) => (
                    <div key={parent.id}>
                      <SelectItem value={parent.id}>{parent.name}</SelectItem>
                      {(parent.children ?? []).map((child) => (
                        <SelectItem key={child.id} value={child.id} className="pl-8">
                          {child.name}
                        </SelectItem>
                      ))}
                    </div>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
        ) : null}

        <Field id="budget-limit" label="Monthly limit" error={fieldErrors.limit}>
          {(props) => (
            <MoneyInput
              {...props}
              currency={currency}
              value={limit}
              onChange={(event) => {
                setLimit(event.target.value)
                setFieldErrors((current) => ({ ...current, limit: undefined }))
              }}
              autoFocus
            />
          )}
        </Field>
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <SubmitButton pending={save.isPending} onClick={attemptSave} type="button">
          {isEdit ? 'Change limit' : 'Set limit'}
        </SubmitButton>
      </DialogFooter>
    </>
  )
}
