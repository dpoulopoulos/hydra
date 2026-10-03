import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { AccountType, goalsCreateGoal, goalsUpdateGoal, type GoalPublic } from '@/api'
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
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAccountCurrency, useAccounts } from '@/hooks/use-accounts'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { refill } from '@/lib/form'
import { useLocale } from '@/lib/locale-context'
import { formatMajorInput } from '@/lib/money'
import { optionSource } from '@/lib/option-source'

/**
 * A function of the currency, because how many minor units a typed target
 * makes depends on the account it is saved in.
 */
function buildSchema(currency: string, locale: string | undefined) {
  return z.object({
    name: z.string().trim().min(1, 'Give the goal a name.').max(100),
    account_id: z.string().min(1, 'Pick the savings account the money goes into.'),
    target: amountSchema(currency, { locale }),
    target_date: z.string(),
  })
}

type Values = z.input<ReturnType<typeof buildSchema>>
type Parsed = z.output<ReturnType<typeof buildSchema>>

export function GoalDialog({
  open,
  goal,
  onOpenChange,
}: {
  open: boolean
  /** The goal being edited, or null when adding one. */
  goal: GoalPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const locale = useLocale()
  const currencyOf = useAccountCurrency()
  const isEdit = goal !== null

  const accountsQuery = useAccounts()
  const accountSource = optionSource(accountsQuery, 'accounts')
  const savingsAccounts = accountSource.options.filter(
    (account) => account.type === AccountType.SAVINGS,
  )

  const form = useForm<Values, unknown, Parsed>({
    resolver: (values, context, options) =>
      zodResolver(buildSchema(currencyOf(values.account_id), locale))(values, context, options),
    defaultValues: { name: '', account_id: '', target: '', target_date: '' },
  })

  const control = form.control
  const accountId = useWatch({ control, name: 'account_id' })
  const currency = currencyOf(accountId)

  useEffect(() => {
    if (!open) return
    refill(form, {
      name: goal?.name ?? '',
      account_id: goal?.account_id ?? '',
      target: goal ? formatMajorInput(goal.target_minor, goal.currency_code, locale) : '',
      target_date: goal?.target_date ?? '',
    })
  }, [open, goal, locale, form])

  const save = useMutation({
    mutationFn: async (values: Parsed) => {
      const body = {
        name: values.name,
        account_id: values.account_id,
        target_minor: values.target,
        target_date: values.target_date || null,
      }

      if (goal) {
        const { error } = await goalsUpdateGoal({ path: { goal_id: goal.id }, body })
        if (error) throw error
        return
      }

      const { error } = await goalsCreateGoal({ body })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['goals'] })
      toast.success(isEdit ? 'Goal saved' : 'Goal added')
      onOpenChange(false)
    },
  })

  const noSavings = !accountSource.unavailable && savingsAccounts.length === 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${goal.name}` : 'Add a goal'}</DialogTitle>
          <DialogDescription>
            Say what you are saving for and how much it costs. Tag transfers into the savings
            account with the goal to fill it.
          </DialogDescription>
        </DialogHeader>

        <form
          id="goal-form"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <Field id="name" label="Name" error={form.formState.errors.name?.message}>
            {(props) => (
              <Input {...props} {...form.register('name')} placeholder="New car" autoFocus />
            )}
          </Field>

          <Field
            id="account_id"
            label="Savings account"
            hint={
              noSavings
                ? 'Add a savings account first. A goal keeps its money in one.'
                : 'Several goals can share one account.'
            }
            error={form.formState.errors.account_id?.message ?? accountSource.error}
          >
            {(props) => (
              <Select
                value={accountId}
                onValueChange={(value) =>
                  form.setValue('account_id', value, { shouldValidate: form.formState.isSubmitted })
                }
                disabled={accountSource.unavailable || noSavings}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue placeholder="Pick an account" />
                </SelectTrigger>
                <SelectContent>
                  {savingsAccounts.map((account) => (
                    <SelectItem key={account.id} value={account.id}>
                      {account.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>

          <Field id="target" label="Price" error={form.formState.errors.target?.message}>
            {(props) => <MoneyInput {...props} {...form.register('target')} currency={currency} />}
          </Field>

          <Field
            id="target_date"
            label="Reach it by"
            hint="Optional. With a date, hydra works out how much to save each month."
            error={form.formState.errors.target_date?.message}
          >
            {(props) => <Input {...props} {...form.register('target_date')} type="date" />}
          </Field>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="goal-form" pending={save.isPending}>
            {isEdit ? 'Save changes' : 'Add goal'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
