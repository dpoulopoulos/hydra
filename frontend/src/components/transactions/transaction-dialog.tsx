import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  CategoryKind,
  transactionsCreateTransaction,
  transactionsUpdateTransaction,
  TransactionKind,
  type TransactionPublic,
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
import { Textarea } from '@/components/ui/textarea'
import { useAccountCurrency, useAccounts } from '@/hooks/use-accounts'
import { useCategoryTree } from '@/hooks/use-categories'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { formatMajorInput } from '@/lib/money'
import { today } from '@/lib/month'
import { optionSource } from '@/lib/option-source'

const NO_CATEGORY = 'none'

/**
 * The form's rules.
 *
 * A function of the currency, because how many minor units a typed amount
 * stands for is a property of the currency the account is kept in.
 */
function buildSchema(currency: string) {
  return z
    .object({
      kind: z.enum(TransactionKind),
      amount: amountSchema(currency),
      occurred_on: z.string().min(1, 'Pick a date.'),
      account_id: z.string().min(1, 'Choose an account.'),
      counter_account_id: z.string(),
      category_id: z.string(),
      merchant: z.string().trim().max(255).optional(),
      note: z.string().trim().max(1024).optional(),
    })
    .superRefine((values, ctx) => {
      // The same shape rules the API enforces, checked here so the reason is
      // shown next to the field rather than as a rejected request.
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
    })
}

type Schema = ReturnType<typeof buildSchema>
type Values = z.input<Schema>
type Parsed = z.output<Schema>

// React Compiler will not memoize a component that calls React Hook Form's
// `watch()`, and skips it whole. That skip is what this form relies on:
// `form.reset()` empties the field map and counts on the next render calling
// `register()` again, which a memoized render never repeats, leaving every
// field unregistered and the form with nothing to save. Nothing goes stale in
// return, since `watch()` re-renders this component and the controls under it
// are handed the value from that render.
/* eslint-disable react-hooks/incompatible-library -- skipping this one is the point; see above */
export function TransactionDialog({
  open,
  transaction,
  onOpenChange,
}: {
  open: boolean
  /** The transaction being edited, or null when recording one. */
  transaction: TransactionPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const isEdit = transaction !== null
  const accountsQuery = useAccounts()
  const currencyOf = useAccountCurrency()

  const form = useForm<Values, unknown, Parsed>({
    // The money moves in the account the values name, so that is the currency
    // the typed amount is read in. Reading it here rather than from a schema
    // fixed at mount keeps the parsing with the account the user has chosen.
    resolver: (values, context, options) =>
      zodResolver(buildSchema(currencyOf(values.account_id)))(values, context, options),
    defaultValues: {
      kind: TransactionKind.EXPENSE,
      amount: '',
      occurred_on: today(),
      account_id: '',
      counter_account_id: '',
      category_id: NO_CATEGORY,
      merchant: '',
      note: '',
    },
  })

  const kind = form.watch('kind')
  const accountId = form.watch('account_id')
  const isTransfer = kind === TransactionKind.TRANSFER
  // What the amount field says it is in, so the account and the figure next to
  // it never disagree about what was typed.
  const currency = currencyOf(accountId)
  // The transaction being edited holds its amount in its own account, which is
  // the one it was recorded against rather than whichever the picker shows.
  const recordedCurrency = currencyOf(transaction?.account_id)

  // An expense needs an expense category and income needs an income one, so
  // the picker only offers the matching kind.
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
    form.reset({
      kind: transaction?.kind ?? TransactionKind.EXPENSE,
      amount: transaction ? formatMajorInput(transaction.amount_minor, recordedCurrency) : '',
      occurred_on: transaction?.occurred_on ?? today(),
      account_id: transaction?.account_id ?? '',
      counter_account_id: transaction?.counter_account_id ?? '',
      category_id: transaction?.category_id ?? NO_CATEGORY,
      merchant: transaction?.merchant ?? '',
      note: transaction?.note ?? '',
    })
  }, [open, transaction, recordedCurrency, form])

  // The accounts can still be on their way when the dialog opens, so the first
  // one is offered as soon as they land. Only the empty picker is filled in:
  // a choice already made, by the user or by the transaction being edited,
  // stands.
  useEffect(() => {
    if (!open || !defaultAccountId) return
    if (form.getValues('account_id')) return
    form.setValue('account_id', defaultAccountId)
  }, [open, defaultAccountId, form])

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      // A transfer moves money between your own accounts, so it carries no
      // category; anything else carries no destination account.
      const body = {
        kind: parsed.kind,
        amount_minor: parsed.amount,
        occurred_on: parsed.occurred_on,
        account_id: parsed.account_id,
        counter_account_id:
          parsed.kind === TransactionKind.TRANSFER ? parsed.counter_account_id : null,
        category_id:
          parsed.kind === TransactionKind.TRANSFER || parsed.category_id === NO_CATEGORY
            ? null
            : parsed.category_id,
        merchant: parsed.merchant || null,
        note: parsed.note || null,
      }

      if (transaction) {
        const { error } = await transactionsUpdateTransaction({
          path: { transaction_id: transaction.id },
          body,
        })
        if (error) throw error
        return
      }

      const { error } = await transactionsCreateTransaction({ body })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      // Balances and every report depend on the ledger.
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(isEdit ? 'Transaction saved' : 'Transaction recorded')
      onOpenChange(false)
    },
  })

  const accountOptions = accountSource.options
  const errors = form.formState.errors

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid-rows-[auto_minmax(0,1fr)_auto] sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit transaction' : 'Record a transaction'}</DialogTitle>
          <DialogDescription>
            {isTransfer
              ? 'Moving money between your own accounts. It counts as neither spending nor income.'
              : 'Money leaving or arriving in one of your accounts.'}
          </DialogDescription>
        </DialogHeader>

        <form
          id="transaction-form"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          className="-mx-1 space-y-4 overflow-y-auto px-1"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <Tabs
            value={kind}
            onValueChange={(value) => {
              form.setValue('kind', value as TransactionKind)
              // The category and destination belong to different kinds.
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

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="amount" label="Amount" error={errors.amount?.message}>
              {(props) => (
                <MoneyInput {...props} {...form.register('amount')} currency={currency} autoFocus />
              )}
            </Field>

            <Field id="occurred_on" label="Date" error={errors.occurred_on?.message}>
              {(props) => <Input {...props} {...form.register('occurred_on')} type="date" />}
            </Field>
          </div>

          <Field
            id="account_id"
            label={isTransfer ? 'From account' : 'Account'}
            error={errors.account_id?.message ?? accountSource.error}
          >
            {(props) => (
              <Select
                value={accountId}
                onValueChange={(value) => form.setValue('account_id', value)}
                disabled={accountSource.unavailable}
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
                  disabled={accountSource.unavailable}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue placeholder="Choose an account" />
                  </SelectTrigger>
                  <SelectContent>
                    {accountOptions
                      .filter((account) => account.id !== accountId)
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
                      <SelectGroupOptions key={parent.id} parent={parent} />
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="merchant" label="Merchant" error={errors.merchant?.message}>
              {(props) => (
                <Input {...props} {...form.register('merchant')} placeholder="Optional" />
              )}
            </Field>

            <Field id="note" label="Note" error={errors.note?.message}>
              {(props) => (
                <Textarea {...props} {...form.register('note')} rows={1} placeholder="Optional" />
              )}
            </Field>
          </div>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="transaction-form" pending={save.isPending}>
            {isEdit ? 'Save changes' : 'Record it'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** A parent category and the subcategories under it, as picker options. */
function SelectGroupOptions({
  parent,
}: {
  parent: { id: string; name: string; children?: { id: string; name: string }[] }
}) {
  return (
    <>
      <SelectItem value={parent.id}>{parent.name}</SelectItem>
      {(parent.children ?? []).map((child) => (
        <SelectItem key={child.id} value={child.id} className="pl-8">
          {child.name}
        </SelectItem>
      ))}
    </>
  )
}
