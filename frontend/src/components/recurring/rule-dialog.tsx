import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  CategoryKind,
  RecurrenceFrequency,
  recurringRulesCreateRecurringRule,
  recurringRulesUpdateRecurringRule,
  TransactionKind,
  type RecurringRulePublic,
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
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAccounts } from '@/hooks/use-accounts'
import { useCategoryTree } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { FREQUENCY_LABELS } from '@/lib/labels'
import { toMajor } from '@/lib/money'
import { today } from '@/lib/month'

const NO_CATEGORY = 'none'

const schema = z
  .object({
    name: z.string().trim().min(1, 'Name the rule, such as Rent or Netflix.').max(255),
    kind: z.enum(TransactionKind),
    amount: amountSchema(),
    frequency: z.enum(RecurrenceFrequency),
    interval: z.coerce.number().int().min(1, 'Repeat at least every one period.').max(60),
    day_of_month: z.string(),
    start_date: z.string().min(1, 'Pick when it starts.'),
    end_date: z.string(),
    account_id: z.string().min(1, 'Choose an account.'),
    counter_account_id: z.string(),
    category_id: z.string(),
    merchant: z.string().trim().max(255).optional(),
  })
  .superRefine((values, ctx) => {
    if (values.kind === TransactionKind.TRANSFER) {
      if (!values.counter_account_id) {
        ctx.addIssue({
          code: 'custom',
          path: ['counter_account_id'],
          message: 'Choose where the money goes.',
        })
      } else if (values.counter_account_id === values.account_id) {
        ctx.addIssue({
          code: 'custom',
          path: ['counter_account_id'],
          message: 'A transfer needs two different accounts.',
        })
      }
    }
    if (values.end_date && values.end_date < values.start_date) {
      ctx.addIssue({
        code: 'custom',
        path: ['end_date'],
        message: 'It cannot end before it starts.',
      })
    }
  })

type Values = z.input<typeof schema>
type Parsed = z.output<typeof schema>

export function RuleDialog({
  open,
  rule,
  onOpenChange,
}: {
  open: boolean
  /** The rule being edited, or null when adding one. */
  rule: RecurringRulePublic | null
  onOpenChange: (open: boolean) => void
}) {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const isEdit = rule !== null
  const { data: accounts } = useAccounts()

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      kind: TransactionKind.EXPENSE,
      amount: '',
      frequency: RecurrenceFrequency.MONTHLY,
      interval: 1,
      day_of_month: '',
      start_date: today(),
      end_date: '',
      account_id: '',
      counter_account_id: '',
      category_id: NO_CATEGORY,
      merchant: '',
    },
  })

  const kind = form.watch('kind')
  const frequency = form.watch('frequency')
  const isTransfer = kind === TransactionKind.TRANSFER
  const isMonthly = frequency !== RecurrenceFrequency.WEEKLY

  const { data: categoryTree } = useCategoryTree({
    kind: kind === TransactionKind.INCOME ? CategoryKind.INCOME : CategoryKind.EXPENSE,
  })

  useEffect(() => {
    if (!open) return
    form.reset({
      name: rule?.name ?? '',
      kind: rule?.kind ?? TransactionKind.EXPENSE,
      amount: rule ? String(toMajor(rule.amount_minor, currency)) : '',
      frequency: rule?.frequency ?? RecurrenceFrequency.MONTHLY,
      interval: rule?.interval ?? 1,
      day_of_month: rule?.day_of_month ? String(rule.day_of_month) : '',
      start_date: rule?.start_date ?? today(),
      end_date: rule?.end_date ?? '',
      account_id: rule?.account_id ?? accounts?.data[0]?.id ?? '',
      counter_account_id: rule?.counter_account_id ?? '',
      category_id: rule?.category_id ?? NO_CATEGORY,
      merchant: rule?.merchant ?? '',
    })
  }, [open, rule, accounts, currency, form])

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      const dayOfMonth = isMonthly && parsed.day_of_month ? Number(parsed.day_of_month) : null
      const categoryId =
        parsed.kind === TransactionKind.TRANSFER || parsed.category_id === NO_CATEGORY
          ? null
          : parsed.category_id

      if (rule) {
        // The API fixes the start date and the accounts once a rule exists,
        // since moving them would not match the transactions already created.
        const { error } = await recurringRulesUpdateRecurringRule({
          path: { rule_id: rule.id },
          body: {
            name: parsed.name,
            amount_minor: parsed.amount,
            frequency: parsed.frequency,
            interval: parsed.interval,
            day_of_month: dayOfMonth,
            end_date: parsed.end_date || null,
            category_id: categoryId,
            merchant: parsed.merchant || null,
          },
        })
        if (error) throw error
        return
      }

      const { error } = await recurringRulesCreateRecurringRule({
        body: {
          name: parsed.name,
          kind: parsed.kind,
          amount_minor: parsed.amount,
          frequency: parsed.frequency,
          interval: parsed.interval,
          day_of_month: dayOfMonth,
          start_date: parsed.start_date,
          end_date: parsed.end_date || null,
          account_id: parsed.account_id,
          counter_account_id: isTransfer ? parsed.counter_account_id : null,
          category_id: categoryId,
          merchant: parsed.merchant || null,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['recurring'] })
      toast.success(isEdit ? 'Rule saved' : 'Rule added')
      onOpenChange(false)
    },
  })

  const errors = form.formState.errors
  const accountOptions = accounts?.data ?? []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${rule.name}` : 'Add a recurring rule'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'The start date and accounts stay as they are, so the transactions already recorded still match.'
              : 'Rent, a subscription, a standing transfer. hydra records each one as it falls due.'}
          </DialogDescription>
        </DialogHeader>

        <form
          id="rule-form"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          {!isEdit ? (
            <Tabs
              value={kind}
              onValueChange={(value) => {
                form.setValue('kind', value as TransactionKind)
                form.setValue('category_id', NO_CATEGORY)
                form.setValue('counter_account_id', '')
              }}
            >
              <TabsList className="w-full">
                <TabsTrigger value={TransactionKind.EXPENSE} className="flex-1">
                  Expense
                </TabsTrigger>
                <TabsTrigger value={TransactionKind.INCOME} className="flex-1">
                  Income
                </TabsTrigger>
                <TabsTrigger value={TransactionKind.TRANSFER} className="flex-1">
                  Transfer
                </TabsTrigger>
              </TabsList>
            </Tabs>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="name" label="Name" error={errors.name?.message}>
              {(props) => (
                <Input {...props} {...form.register('name')} placeholder="Rent" autoFocus />
              )}
            </Field>

            <Field id="amount" label="Amount" error={errors.amount?.message}>
              {(props) => (
                <MoneyInput {...props} {...form.register('amount')} currency={currency} />
              )}
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="frequency" label="Repeats" error={errors.frequency?.message}>
              {(props) => (
                <Select
                  value={frequency}
                  onValueChange={(value) =>
                    form.setValue('frequency', value as RecurrenceFrequency)
                  }
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.values(RecurrenceFrequency).map((value) => (
                      <SelectItem key={value} value={value}>
                        {FREQUENCY_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>

            <Field
              id="interval"
              label="Every"
              hint={frequency === RecurrenceFrequency.WEEKLY ? 'weeks' : undefined}
              error={errors.interval?.message}
            >
              {(props) => (
                <Input {...props} {...form.register('interval')} type="number" min={1} max={60} />
              )}
            </Field>

            {isMonthly ? (
              <Field
                id="day_of_month"
                label="On day"
                hint="A day past the end of a short month falls back to its last day."
                error={errors.day_of_month?.message}
              >
                {(props) => (
                  <Input
                    {...props}
                    {...form.register('day_of_month')}
                    type="number"
                    min={1}
                    max={31}
                    placeholder="Same as start"
                  />
                )}
              </Field>
            ) : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="start_date" label="Starts" error={errors.start_date?.message}>
              {(props) => (
                <Input {...props} {...form.register('start_date')} type="date" disabled={isEdit} />
              )}
            </Field>

            <Field
              id="end_date"
              label="Ends"
              hint="Leave empty to keep going."
              error={errors.end_date?.message}
            >
              {(props) => <Input {...props} {...form.register('end_date')} type="date" />}
            </Field>
          </div>

          <Field
            id="account_id"
            label={isTransfer ? 'From account' : 'Account'}
            error={errors.account_id?.message}
          >
            {(props) => (
              <Select
                value={form.watch('account_id')}
                onValueChange={(value) => form.setValue('account_id', value)}
                disabled={isEdit}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue placeholder="Choose an account" />
                </SelectTrigger>
                <SelectContent>
                  {accountOptions.map((account) => (
                    <SelectItem key={account.id} value={account.id}>
                      {account.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>

          {isTransfer ? (
            <Field
              id="counter_account_id"
              label="To account"
              error={errors.counter_account_id?.message}
            >
              {(props) => (
                <Select
                  value={form.watch('counter_account_id')}
                  onValueChange={(value) => form.setValue('counter_account_id', value)}
                  disabled={isEdit}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue placeholder="Choose an account" />
                  </SelectTrigger>
                  <SelectContent>
                    {accountOptions
                      .filter((account) => account.id !== form.watch('account_id'))
                      .map((account) => (
                        <SelectItem key={account.id} value={account.id}>
                          {account.name}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          ) : (
            <Field id="category_id" label="Category" error={errors.category_id?.message}>
              {(props) => (
                <Select
                  value={form.watch('category_id')}
                  onValueChange={(value) => form.setValue('category_id', value)}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_CATEGORY}>Leave uncategorised</SelectItem>
                    {(categoryTree?.data ?? []).map((parent) => (
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
          )}

          <Field id="merchant" label="Merchant" error={errors.merchant?.message}>
            {(props) => <Input {...props} {...form.register('merchant')} placeholder="Optional" />}
          </Field>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="rule-form" pending={save.isPending}>
            {isEdit ? 'Save changes' : 'Add rule'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
