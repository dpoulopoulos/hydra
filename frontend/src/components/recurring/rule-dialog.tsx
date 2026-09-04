import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
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
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { FormSection as Section } from '@/components/form-section'
import { Separator } from '@/components/ui/separator'
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
import { amountSchema, parseMajor } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { describeSchedule, FREQUENCY_LABELS } from '@/lib/labels'
import { formatMajorInput, formatMoney, toMinor } from '@/lib/money'
import { formatDate, today } from '@/lib/month'
import { optionSource } from '@/lib/option-source'
import { cn } from '@/lib/utils'

const NO_CATEGORY = 'none'

/**
 * The form's rules.
 *
 * A function of the currency, because how many minor units a typed amount
 * stands for is a property of the currency the household keeps its books in.
 */
function buildSchema(currency: string) {
  return z
    .object({
      name: z.string().trim().min(1, 'Name the rule, such as Rent or Netflix.').max(255),
      kind: z.enum(TransactionKind),
      amount: amountSchema(currency),
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
}

type Schema = ReturnType<typeof buildSchema>
type Values = z.input<Schema>
type Parsed = z.output<Schema>

/**
 * What the rule will do, in a sentence.
 *
 * The fields above can stay terse because this says the whole thing back in
 * plain words, which is also where a reader learns what an empty "on day" or
 * an interval of 3 actually means.
 */
function describeRule({
  kind,
  amount,
  currency,
  frequency,
  interval,
  dayOfMonth,
  startDate,
  endDate,
  from,
  to,
  category,
}: {
  kind: TransactionKind
  amount: string
  currency: string
  frequency: RecurrenceFrequency
  interval: number
  dayOfMonth: number | null
  startDate: string
  endDate: string
  from: string | undefined
  to: string | undefined
  category: string | undefined
}): string | null {
  // The parser the field itself validates with, so the sentence quotes the
  // figure that would be saved rather than one of its own reading.
  const major = parseMajor(amount)
  if (major === null || major <= 0 || !startDate) return null

  const money = formatMoney(toMinor(major, currency), currency)
  const schedule = describeSchedule(frequency, interval, dayOfMonth).toLowerCase()
  const head =
    kind === TransactionKind.TRANSFER
      ? `${money} moves${from && to ? ` from ${from} to ${to}` : from ? ` out of ${from}` : ''}`
      : kind === TransactionKind.INCOME
        ? `${money} arrives${from ? ` in ${from}` : ''}`
        : `${money} leaves${from ? ` ${from}` : ''}`

  let sentence = `${head} ${schedule}, starting ${formatDate(startDate)}.`
  if (endDate) sentence += ` It stops after ${formatDate(endDate)}.`
  if (category && kind !== TransactionKind.TRANSFER) sentence += ` Filed under ${category}.`
  return sentence
}

// React Compiler will not memoize a component that calls React Hook Form's
// `watch()`, and skips it whole. That skip is what this form relies on:
// `form.reset()` empties the field map and counts on the next render calling
// `register()` again, which a memoized render never repeats, leaving every
// field unregistered and the form with nothing to save. Nothing goes stale in
// return, since `watch()` re-renders this component and the controls under it
// are handed the value from that render.
/* eslint-disable react-hooks/incompatible-library -- skipping this one is the point; see above */
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
  const schema = useMemo(() => buildSchema(currency), [currency])
  const queryClient = useQueryClient()
  const isEdit = rule !== null
  const accountsQuery = useAccounts()
  const [showMore, setShowMore] = useState(false)

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

  const categoriesQuery = useCategoryTree({
    kind: kind === TransactionKind.INCOME ? CategoryKind.INCOME : CategoryKind.EXPENSE,
  })

  // A picker with nothing in it says the household has no accounts. When the
  // list was refused rather than empty, the field says so instead.
  const accountSource = optionSource(accountsQuery, 'accounts')
  const categorySource = optionSource(categoriesQuery, 'categories')

  // A balance is computed from the ledger, so the account list comes back as a
  // new object whenever anything in the household moves. Keeping the payload
  // out of the effects below means a refetch behind an open dialog never
  // reaches the form the user is filling in.
  const defaultAccountId = accountSource.options[0]?.id ?? ''

  useEffect(() => {
    if (!open) return
    setShowMore(Boolean(rule && ((rule.interval ?? 1) > 1 || rule.end_date || rule.merchant)))
    form.reset({
      name: rule?.name ?? '',
      kind: rule?.kind ?? TransactionKind.EXPENSE,
      amount: rule ? formatMajorInput(rule.amount_minor, currency) : '',
      frequency: rule?.frequency ?? RecurrenceFrequency.MONTHLY,
      interval: rule?.interval ?? 1,
      day_of_month: rule?.day_of_month ? String(rule.day_of_month) : '',
      start_date: rule?.start_date ?? today(),
      end_date: rule?.end_date ?? '',
      account_id: rule?.account_id ?? '',
      counter_account_id: rule?.counter_account_id ?? '',
      category_id: rule?.category_id ?? NO_CATEGORY,
      merchant: rule?.merchant ?? '',
    })
  }, [open, rule, currency, form])

  // The accounts can still be on their way when the dialog opens, so the first
  // one is offered as soon as they land. Only the empty picker is filled in: a
  // choice already made, by the user or by the rule being edited, stands.
  useEffect(() => {
    if (!open || !defaultAccountId) return
    if (form.getValues('account_id')) return
    form.setValue('account_id', defaultAccountId)
  }, [open, defaultAccountId, form])

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
  const accountOptions = accountSource.options
  const nameOf = (id: string) => accountOptions.find((account) => account.id === id)?.name
  const categoryName = (() => {
    const id = form.watch('category_id')
    if (id === NO_CATEGORY) return undefined
    for (const parent of categorySource.options) {
      if (parent.id === id) return parent.name
      const child = (parent.children ?? []).find((candidate) => candidate.id === id)
      if (child) return `${parent.name} › ${child.name}`
    }
    return undefined
  })()

  const summary = describeRule({
    kind,
    amount: form.watch('amount'),
    currency,
    frequency,
    interval: Number(form.watch('interval')) || 1,
    dayOfMonth: isMonthly && form.watch('day_of_month') ? Number(form.watch('day_of_month')) : null,
    startDate: form.watch('start_date'),
    endDate: form.watch('end_date'),
    from: nameOf(form.watch('account_id')),
    to: nameOf(form.watch('counter_account_id')),
    category: categoryName,
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* The form is long enough to outgrow a phone screen, so it scrolls
          inside the dialog while the title and the buttons stay put. */}
      <DialogContent className="grid-rows-[auto_minmax(0,1fr)_auto] gap-5 sm:max-w-2xl sm:p-6">
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
          className="-mx-1 space-y-6 overflow-y-auto px-1"
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

          <Section title="What it is">
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

            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                id="account_id"
                label={isTransfer ? 'From account' : 'Account'}
                error={errors.account_id?.message ?? accountSource.error}
              >
                {(props) => (
                  <Select
                    value={form.watch('account_id')}
                    onValueChange={(value) => form.setValue('account_id', value)}
                    disabled={isEdit || accountSource.unavailable}
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
                  error={errors.counter_account_id?.message ?? accountSource.error}
                >
                  {(props) => (
                    <Select
                      value={form.watch('counter_account_id')}
                      onValueChange={(value) => form.setValue('counter_account_id', value)}
                      disabled={isEdit || accountSource.unavailable}
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
                <Field
                  id="category_id"
                  label="Category"
                  error={errors.category_id?.message ?? categorySource.error}
                >
                  {(props) => (
                    <Select
                      value={form.watch('category_id')}
                      onValueChange={(value) => form.setValue('category_id', value)}
                      disabled={categorySource.unavailable}
                    >
                      <SelectTrigger id={props.id} className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_CATEGORY}>Leave uncategorised</SelectItem>
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
              )}
            </div>
          </Section>

          <Separator />

          <Section title="When it happens">
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

              <Field id="start_date" label="Starts" error={errors.start_date?.message}>
                {(props) => (
                  <Input
                    {...props}
                    {...form.register('start_date')}
                    type="date"
                    disabled={isEdit}
                  />
                )}
              </Field>

              {isMonthly ? (
                <Field
                  id="day_of_month"
                  label="On day"
                  // The short-month rule only matters once a day can miss one.
                  hint={
                    Number(form.watch('day_of_month')) > 28
                      ? 'Short months use their last day.'
                      : undefined
                  }
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
          </Section>

          {/* Three fields most rules never touch. Whatever is set in here still
              shows up in the sentence below, so nothing hides silently. */}
          <Collapsible open={showMore} onOpenChange={setShowMore}>
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground -ml-2 h-8"
              >
                <ChevronDown
                  className={cn('size-4 transition-transform', showMore && 'rotate-180')}
                />
                More options
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3">
              <div className="grid gap-4 sm:grid-cols-3">
                <Field
                  id="interval"
                  label="Every"
                  hint={frequency === RecurrenceFrequency.WEEKLY ? 'weeks' : 'months or years'}
                  error={errors.interval?.message}
                >
                  {(props) => (
                    <Input
                      {...props}
                      {...form.register('interval')}
                      type="number"
                      min={1}
                      max={60}
                    />
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

                <Field id="merchant" label="Merchant" error={errors.merchant?.message}>
                  {(props) => (
                    <Input {...props} {...form.register('merchant')} placeholder="Optional" />
                  )}
                </Field>
              </div>
            </CollapsibleContent>
          </Collapsible>

          {summary ? (
            <p className="bg-muted text-muted-foreground rounded-lg px-3 py-2 text-sm">{summary}</p>
          ) : null}
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
