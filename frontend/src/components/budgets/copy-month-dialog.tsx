import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { budgetsCopyBudgets, CategoryKind } from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { FormError } from '@/components/form-field'
import { SubmitButton } from '@/components/submit-button'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMonthBudgets } from '@/hooks/use-budgets'
import { useCategoryTree } from '@/hooks/use-categories'
import { errorMessage } from '@/lib/api'
import { removedLimits } from '@/lib/budgets'
import { formatMonth, shiftMonth } from '@/lib/month'

/**
 * Whether an answer is in hand and current.
 *
 * A query still fetching in the background holds the previous answer, which a
 * replace would work its removals out from: the list would name the categories
 * the months used to have, not the ones they have now.
 */
function arrived(query: { isSuccess: boolean; isFetching: boolean }): boolean {
  return query.isSuccess && !query.isFetching
}

/** The category ids a month has budgeted. */
function budgetedIn(budgets: { category_id: string }[] | undefined): string[] {
  return (budgets ?? []).map((budget) => budget.category_id)
}

/**
 * Copy a month of limits onto this one.
 *
 * Budgets deliberately do not roll over, so without this "same as last month"
 * would mean retyping every limit.
 */
export function CopyMonthDialog({
  open,
  month,
  onOpenChange,
}: {
  open: boolean
  /** The month being copied onto. */
  month: string
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const [from, setFrom] = useState(() => shiftMonth(month, -1))
  const [overwrite, setOverwrite] = useState(false)
  // The removals a replace would make, held back until they are agreed to.
  const [pendingRemoval, setPendingRemoval] = useState<string[] | null>(null)

  // Archived categories included: a replace deletes every limit the source
  // month does not set, archived or not, so leaving them out of the tree would
  // leave them out of the list as well.
  const tree = useCategoryTree(
    { kind: CategoryKind.EXPENSE, includeArchived: true },
    { enabled: open },
  )
  // Both months, so what a replace removes can be named before it is sent: the
  // limits this month has that the other one does not.
  const target = useMonthBudgets(month, { enabled: open })
  const source = useMonthBudgets(from, { enabled: open })

  const copy = useMutation({
    mutationFn: async () => {
      const { error } = await budgetsCopyBudgets({
        body: { from_month: from, to_month: month, overwrite },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['budgets'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(`Copied ${formatMonth(from)} onto ${formatMonth(month)}`)
      close()
    },
    // Dropping the confirmation puts the dialog's own error line back in view:
    // a message under the confirmation would be covered by it.
    onError: () => setPendingRemoval(null),
  })

  /** Close the dialog, and forget the removals it was asking about. */
  const close = () => {
    setPendingRemoval(null)
    onOpenChange(false)
  }

  // The six months before this one is as far back as anyone reaches for.
  const options = Array.from({ length: 6 }, (_, index) => shiftMonth(month, -(index + 1)))

  // Only a replace reads the two months and the names to call their categories
  // by, so a copy that adds to the month is still offered when they are slow or
  // gone.
  const describable = [tree, target, source].every(arrived)
  const unreadable = overwrite && (tree.isError || target.isError || source.isError)

  /**
   * Send the copy, unless it would take limits away without saying which.
   *
   * A replace deletes every limit the source month does not set, so the
   * categories left unbudgeted are named first. Without the replace nothing is
   * removed and the copy goes straight out.
   */
  const attemptCopy = () => {
    const removing = overwrite
      ? removedLimits(
          tree.data?.data ?? [],
          budgetedIn(target.data?.data),
          budgetedIn(source.data?.data),
        )
      : []

    if (removing.length > 0) {
      setPendingRemoval(removing)
      return
    }

    copy.mutate()
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
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Copy budgets onto {formatMonth(month)}</DialogTitle>
            <DialogDescription>
              Take the limits from an earlier month instead of setting them again.
            </DialogDescription>
          </DialogHeader>

          <FormError
            message={
              unreadable
                ? 'What these months already have did not load, so a replace cannot say which limits it would remove. Try again, or copy without replacing.'
                : copy.isError
                  ? errorMessage(copy.error)
                  : null
            }
          />

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="from-month">Copy from</Label>
              <Select value={from} onValueChange={setFrom}>
                <SelectTrigger id="from-month" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {options.map((option) => (
                    <SelectItem key={option} value={option}>
                      {formatMonth(option)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-start gap-3">
              <Checkbox
                id="overwrite"
                checked={overwrite}
                onCheckedChange={(checked) => setOverwrite(checked === true)}
              />
              <div className="space-y-1">
                <Label htmlFor="overwrite">Replace the limits already set</Label>
                <p className="text-muted-foreground text-sm">
                  {formatMonth(month)} becomes a copy of {formatMonth(from)}: a limit that{' '}
                  {formatMonth(from)} does not set is removed. Without this, the copy is refused if{' '}
                  {formatMonth(month)} already has budgets.
                </p>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={close}>
              Cancel
            </Button>
            <SubmitButton
              pending={copy.isPending}
              // A replace is only safe to send once both months and the
              // category tree are here: the removals it makes cannot be listed
              // from a month, or a set of names, that never arrived.
              disabled={overwrite && !describable}
              onClick={attemptCopy}
              type="button"
            >
              Copy budgets
            </SubmitButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Outside the dialog rather than inside it, so the two do not fight
          over the focus trap while both are on screen. */}
      <ConfirmDialog
        open={pendingRemoval !== null}
        onOpenChange={(next) => {
          if (!next) setPendingRemoval(null)
        }}
        title={
          pendingRemoval?.length === 1
            ? `Stop budgeting ${pendingRemoval[0]}?`
            : `Stop budgeting ${pendingRemoval?.length ?? 0} categories?`
        }
        description={
          <>
            {formatMonth(from)} sets no limit for{' '}
            <strong className="font-medium">{pendingRemoval?.join(', ')}</strong>, so copying over{' '}
            {formatMonth(month)} takes theirs away. Spending there is still recorded, it is simply
            no longer measured against a budget.
          </>
        }
        confirmLabel="Remove and copy"
        pending={copy.isPending}
        onConfirm={() => copy.mutate()}
      />
    </>
  )
}
