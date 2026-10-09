import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  bankAcceptBankTransaction,
  BankDirection,
  type BankTransactionPublic,
  CategoryKind,
  TransactionKind,
} from '@/api'
import { Field, FormError } from '@/components/form-field'
import { Money } from '@/components/money'
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
import { useAccounts } from '@/hooks/use-accounts'
import { useCategoryTree } from '@/hooks/use-categories'
import { useGoals } from '@/hooks/use-goals'
import { errorMessage } from '@/lib/api'
import { refill } from '@/lib/form'
import { formatDate } from '@/lib/month'
import { optionSource } from '@/lib/option-source'

const NO_CATEGORY = 'none'
const NO_GOAL = 'none'

const schema = z
  .object({
    kind: z.enum(TransactionKind),
    category_id: z.string(),
    counter_account_id: z.string(),
    goal_id: z.string(),
    merchant: z.string().trim().max(255),
    note: z.string().trim().max(1024),
  })
  .superRefine((values, ctx) => {
    if (values.kind === TransactionKind.TRANSFER && !values.counter_account_id) {
      ctx.addIssue({
        code: 'custom',
        path: ['counter_account_id'],
        message: 'Choose the other account.',
      })
    }
  })

type Values = z.infer<typeof schema>

/** The two kinds money moving in one direction can be. */
function kindsFor(direction: BankDirection) {
  return direction === BankDirection.DEBIT
    ? [
        { kind: TransactionKind.EXPENSE, label: 'Expense' },
        { kind: TransactionKind.TRANSFER, label: 'Transfer out' },
      ]
    : [
        { kind: TransactionKind.INCOME, label: 'Income' },
        { kind: TransactionKind.TRANSFER, label: 'Transfer in' },
      ]
}

/** What the form starts as for a row: the bank's own words, kept. */
function initialValues(row: BankTransactionPublic | null): Values {
  return {
    kind:
      row?.direction === BankDirection.CREDIT ? TransactionKind.INCOME : TransactionKind.EXPENSE,
    category_id: NO_CATEGORY,
    counter_account_id: '',
    goal_id: NO_GOAL,
    merchant: row?.counterparty_name ?? '',
    note: row?.description ?? '',
  }
}

/**
 * Put a bank row in the ledger.
 *
 * The amount, the date and the account are the bank's, so only what the bank
 * cannot know is asked: what kind of money it was, and where it belongs.
 */
export function AcceptDialog({
  row,
  onOpenChange,
}: {
  /** The row being accepted, or null when the dialog is closed. */
  row: BankTransactionPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const open = row !== null
  const direction = row?.direction ?? BankDirection.DEBIT

  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: initialValues(row) })
  const control = form.control
  const kind = useWatch({ control, name: 'kind' })
  const categoryId = useWatch({ control, name: 'category_id' })
  const counterAccountId = useWatch({ control, name: 'counter_account_id' })
  const goalId = useWatch({ control, name: 'goal_id' })
  const isTransfer = kind === TransactionKind.TRANSFER

  useEffect(() => {
    if (open) refill(form, initialValues(row))
  }, [open, row, form])

  const accountsQuery = useAccounts()
  const accountSource = optionSource(accountsQuery, 'accounts')
  const linkedName = accountSource.options.find((account) => account.id === row?.account_id)?.name
  const counterOptions = accountSource.options.filter((account) => account.id !== row?.account_id)

  const categoriesQuery = useCategoryTree(
    { kind: direction === BankDirection.CREDIT ? CategoryKind.INCOME : CategoryKind.EXPENSE },
    { enabled: open },
  )
  const categorySource = optionSource(categoriesQuery, 'categories')

  const goalsQuery = useGoals({ enabled: open && isTransfer })
  const goalOptions = (goalsQuery.data?.data ?? []).filter(
    (goal) =>
      (goal.account_id === row?.account_id || goal.account_id === counterAccountId) &&
      !goal.achieved_at,
  )

  const accept = useMutation({
    mutationFn: async (values: Values) => {
      if (!row) return
      const transfer = values.kind === TransactionKind.TRANSFER
      const { error } = await bankAcceptBankTransaction({
        path: { bank_transaction_id: row.id },
        body: {
          kind: values.kind,
          category_id: transfer || values.category_id === NO_CATEGORY ? null : values.category_id,
          counter_account_id: transfer ? values.counter_account_id : null,
          goal_id:
            transfer && goalOptions.some((goal) => goal.id === values.goal_id)
              ? values.goal_id
              : null,
          merchant: values.merchant || null,
          note: values.note || null,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bank', 'inbox'] })
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      void queryClient.invalidateQueries({ queryKey: ['goals'] })
      toast.success('Added to your ledger')
      onOpenChange(false)
    },
  })

  const errors = form.formState.errors

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid-rows-[auto_minmax(0,1fr)_auto] sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Accept into your ledger</DialogTitle>
          <DialogDescription>
            {row ? (
              <>
                <Money
                  minor={direction === BankDirection.DEBIT ? -row.amount_minor : row.amount_minor}
                  currency={row.currency_code}
                  signed
                  colored
                />{' '}
                on {formatDate(row.occurred_on)},{' '}
                {direction === BankDirection.DEBIT ? 'from' : 'into'}{' '}
                {linkedName ?? 'the linked account'}.
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>

        <form
          id="accept-form"
          onSubmit={form.handleSubmit((values) => accept.mutate(values))}
          className="-mx-1 space-y-4 overflow-y-auto px-1"
          noValidate
        >
          <FormError message={accept.isError ? errorMessage(accept.error) : null} />

          <Tabs
            value={kind}
            onValueChange={(value) => {
              form.setValue('kind', value as TransactionKind)
              form.setValue('category_id', NO_CATEGORY)
              form.setValue('counter_account_id', '')
            }}
          >
            <TabsList className="w-full">
              {kindsFor(direction).map((option) => (
                <TabsTrigger key={option.kind} value={option.kind} className="flex-1">
                  {option.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          {isTransfer ? (
            <Field
              id="accept-counter-account"
              label={direction === BankDirection.DEBIT ? 'To account' : 'From account'}
              error={errors.counter_account_id?.message ?? accountSource.error}
            >
              {(props) => (
                <Select
                  value={counterAccountId}
                  // Checked again on the pick, so a complaint from a refused
                  // submit goes away once there is an account to send.
                  onValueChange={(value) =>
                    form.setValue('counter_account_id', value, { shouldValidate: true })
                  }
                  disabled={accountSource.unavailable}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue placeholder="Choose an account" />
                  </SelectTrigger>
                  <SelectContent>
                    {counterOptions.map((account) => (
                      <SelectItem key={account.id} value={account.id}>
                        {account.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          ) : (
            <Field id="accept-category" label="Category" error={categorySource.error}>
              {(props) => (
                <Select
                  value={categoryId}
                  onValueChange={(value) => form.setValue('category_id', value)}
                  disabled={categorySource.unavailable}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_CATEGORY}>Leave uncategorised</SelectItem>
                    {categorySource.options.map((parent) => (
                      <CategoryOptions key={parent.id} parent={parent} />
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          )}

          {isTransfer && goalOptions.length > 0 ? (
            <Field
              id="accept-goal"
              label="Goal"
              hint="Which goal this money is for. Leave it out to keep it unassigned."
            >
              {(props) => (
                <Select value={goalId} onValueChange={(value) => form.setValue('goal_id', value)}>
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={NO_GOAL}>No goal</SelectItem>
                    {goalOptions.map((goal) => (
                      <SelectItem key={goal.id} value={goal.id}>
                        {goal.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          ) : null}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="accept-merchant" label="Merchant" error={errors.merchant?.message}>
              {(props) => (
                <Input {...props} {...form.register('merchant')} placeholder="Optional" />
              )}
            </Field>
            <Field id="accept-note" label="Note" error={errors.note?.message}>
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
          <SubmitButton form="accept-form" pending={accept.isPending}>
            Accept
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** A parent category and the subcategories under it, as picker options. */
function CategoryOptions({
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
