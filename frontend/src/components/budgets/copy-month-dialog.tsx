import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { budgetsCopyBudgets } from '@/api'
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
import { errorMessage } from '@/lib/api'
import { formatMonth, shiftMonth } from '@/lib/month'

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
      onOpenChange(false)
    },
  })

  // The six months before this one is as far back as anyone reaches for.
  const options = Array.from({ length: 6 }, (_, index) => shiftMonth(month, -(index + 1)))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Copy budgets onto {formatMonth(month)}</DialogTitle>
          <DialogDescription>
            Take the limits from an earlier month instead of setting them again.
          </DialogDescription>
        </DialogHeader>

        <FormError message={copy.isError ? errorMessage(copy.error) : null} />

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
              <Label htmlFor="overwrite">Replace limits already set</Label>
              <p className="text-muted-foreground text-sm">
                Without this, the copy is refused if {formatMonth(month)} already has budgets.
              </p>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton pending={copy.isPending} onClick={() => copy.mutate()} type="button">
            Copy budgets
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
