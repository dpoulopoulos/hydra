import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'

import { budgetsBulkUpsertBudgets, CategoryKind } from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ErrorState, LoadingRows } from '@/components/data-state'
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
import { useMonthBudgets } from '@/hooks/use-budgets'
import { useCategoryTree } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { removedLimits } from '@/lib/budgets'
import { useLocale } from '@/lib/locale-context'
import { formatMajorInput } from '@/lib/money'
import { formatMonth } from '@/lib/month'
import { cn } from '@/lib/utils'

type BudgetEntry = { category_id: string; limit_minor: number }

/**
 * Read the fields into the set the month will be replaced with.
 *
 * Every amount goes through the shared schema, which takes "1 000" and
 * "42,50" as people type them, so the only values reported back are ones
 * nobody could read as a number. An empty field is not one of them: emptying a
 * field is how a category stops being budgeted.
 */
function readLimits(
  limits: Record<string, string>,
  currency: string,
  locale: string | undefined,
): { entries: BudgetEntry[]; errors: Record<string, string> } {
  const entries: BudgetEntry[] = []
  const errors: Record<string, string> = {}

  for (const [category_id, value] of Object.entries(limits)) {
    if (value.trim() === '') continue

    const amount = amountSchema(currency, { allowZero: true, locale }).safeParse(value)

    if (!amount.success) {
      errors[category_id] = amount.error.issues[0].message
      continue
    }

    // A zero limit is the same request as an empty field: stop budgeting this.
    if (amount.data > 0) entries.push({ category_id, limit_minor: amount.data })
  }

  return { entries, errors }
}

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
  const locale = useLocale()
  const queryClient = useQueryClient()
  const { data: tree } = useCategoryTree({ kind: CategoryKind.EXPENSE })
  // Edits are held separately from the saved figures, so the field values can
  // be derived rather than copied into state by an effect, which would set
  // state during render and cascade.
  const [edits, setEdits] = useState<Record<string, string>>({})
  // What a field got wrong, by category. Filled on a save attempt rather than
  // while typing, since half-typed amounts are not mistakes.
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  // A save held back until the removals it carries are confirmed. Holding the
  // entries alongside the names means the set that was described is the set
  // that gets sent.
  const [pendingSave, setPendingSave] = useState<{
    entries: BudgetEntry[]
    removing: string[]
  } | null>(null)

  const existing = useMonthBudgets(month, { enabled: open })

  const saved = useMemo(
    () =>
      Object.fromEntries(
        (existing.data?.data ?? []).map((budget) => [
          budget.category_id,
          formatMajorInput(budget.limit_minor, currency, locale),
        ]),
      ),
    [existing.data, currency, locale],
  )

  /** Record what was typed in a field, and drop any complaint about it. */
  const setLimit = (categoryId: string, value: string) => {
    setEdits((current) => ({ ...current, [categoryId]: value }))
    setFieldErrors((current) =>
      Object.fromEntries(Object.entries(current).filter(([key]) => key !== categoryId)),
    )
  }

  /** What a field shows: the edit if there is one, otherwise the saved limit. */
  const valueFor = (categoryId: string) => edits[categoryId] ?? saved[categoryId] ?? ''

  const limits = { ...saved, ...edits }
  const parents = tree?.data ?? []

  /**
   * Close the dialog and forget what was typed.
   *
   * Every way out goes through here, Cancel and a finished save included: an
   * edit the user backed out of, or one already written to the month, would
   * otherwise still be in the set the next save replaces the month with.
   */
  const close = () => {
    setEdits({})
    setFieldErrors({})
    setPendingSave(null)
    onOpenChange(false)
  }

  const save = useMutation({
    mutationFn: async (entries: BudgetEntry[]) => {
      const { error } = await budgetsBulkUpsertBudgets({ body: { month, entries } })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['budgets'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(`Budgets set for ${formatMonth(month)}`)
      close()
    },
    // A toast rather than the editor's own error line: when a save fails
    // behind the confirmation, the editor is covered and an inline message
    // would never be seen.
    onError: (error) => toast.error(errorMessage(error)),
  })

  /**
   * Send the month, unless a field cannot be read or a limit would be lost.
   *
   * An amount that does not parse is reported rather than skipped: skipping it
   * would drop the category from the set, and a category left out of the set
   * has its limit deleted.
   *
   * Emptying a field is a request to delete, so the removals it adds up to are
   * put back to the user first. The set is worked out once and kept, so the
   * confirmation and the request cannot describe different months.
   */
  const attemptSave = () => {
    const { entries, errors } = readLimits(limits, currency, locale)
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    const removing = removedLimits(
      parents,
      Object.keys(saved),
      entries.map((entry) => entry.category_id),
    )
    if (removing.length > 0) {
      setPendingSave({ entries, removing })
      return
    }

    save.mutate(entries)
  }

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (next) onOpenChange(true)
          else close()
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

          <FormError
            message={
              Object.keys(fieldErrors).length > 0
                ? 'Some amounts could not be read. Check the fields marked below.'
                : null
            }
          />

          {existing.isPending ? (
            <LoadingRows rows={5} />
          ) : existing.isError ? (
            <ErrorState error={existing.error} title="These budgets did not load" />
          ) : (
            <ScrollArea className="-mx-2 max-h-[50vh] px-2">
              <div className="space-y-4">
                {parents.map((parent) => (
                  <div key={parent.id} className="space-y-2">
                    <LimitRow
                      categoryId={parent.id}
                      name={parent.name}
                      currency={currency}
                      value={valueFor(parent.id)}
                      error={fieldErrors[parent.id]}
                      onChange={(value) => setLimit(parent.id, value)}
                    />
                    {(parent.children ?? []).map((child) => (
                      <LimitRow
                        key={child.id}
                        categoryId={child.id}
                        name={child.name}
                        currency={currency}
                        value={valueFor(child.id)}
                        error={fieldErrors[child.id]}
                        onChange={(value) => setLimit(child.id, value)}
                        nested
                      />
                    ))}
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={close}>
              Cancel
            </Button>
            {/* Saving replaces the month with what is on screen, so there is
                nothing safe to send until the saved limits are here: a set
                built from an empty or failed load would delete every one of
                them. */}
            {existing.isSuccess ? (
              <SubmitButton pending={save.isPending} onClick={attemptSave} type="button">
                Save budgets
              </SubmitButton>
            ) : null}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Outside the editor rather than inside it, so the two dialogs do not
          fight over the focus trap while both are on screen. */}
      <ConfirmDialog
        open={pendingSave !== null}
        onOpenChange={(next) => {
          if (!next) setPendingSave(null)
        }}
        title={
          pendingSave?.removing.length === 1
            ? `Stop budgeting ${pendingSave.removing[0]}?`
            : `Stop budgeting ${pendingSave?.removing.length ?? 0} categories?`
        }
        description={
          <>
            {formatMonth(month)} keeps no limit for{' '}
            <strong className="font-medium">{pendingSave?.removing.join(', ')}</strong>. Spending
            there is still recorded, it is simply no longer measured against a budget.
          </>
        }
        confirmLabel="Remove and save"
        pending={save.isPending}
        onConfirm={() => {
          if (pendingSave) save.mutate(pendingSave.entries)
        }}
      />
    </>
  )
}

/**
 * One category's limit field.
 *
 * Both levels of the tree render the same row, a subcategory only indented and
 * set in lighter type, so the two stay in step.
 */
function LimitRow({
  categoryId,
  name,
  currency,
  value,
  error,
  nested = false,
  onChange,
}: {
  categoryId: string
  name: string
  currency: string
  value: string
  /** What this field got wrong, shown under it. */
  error?: string
  /** Whether this is a subcategory, shown under its parent. */
  nested?: boolean
  onChange: (value: string) => void
}) {
  const id = `limit-${categoryId}`
  const errorId = `${id}-error`

  return (
    <div className={cn('space-y-1', nested && 'pl-4')}>
      <div className="flex items-center gap-3">
        <Label
          htmlFor={id}
          className={cn('flex-1', nested ? 'text-muted-foreground font-normal' : 'font-medium')}
        >
          {name}
        </Label>
        <MoneyInput
          id={id}
          currency={currency}
          className="w-40"
          value={value}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
      {error ? (
        <p id={errorId} className="text-destructive text-right text-sm">
          {error}
        </p>
      ) : null}
    </div>
  )
}
