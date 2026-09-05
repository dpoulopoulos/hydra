import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  AccountType,
  accountsCreateAccount,
  accountsUpdateAccount,
  type AccountPublic,
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
import { useCurrency } from '@/hooks/use-household'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { compactIban, formatIban, isValidIban } from '@/lib/iban'
import { ACCOUNT_TYPE_LABELS } from '@/lib/labels'
import { toMajor } from '@/lib/money'
import { today } from '@/lib/month'

const schema = z.object({
  name: z.string().trim().min(1, 'Give the account a name.').max(255),
  type: z.enum(AccountType),
  institution: z.string().trim().max(255).optional(),
  iban: z
    .string()
    .trim()
    .transform(compactIban)
    .refine((value) => value === '' || isValidIban(value), {
      message: 'Check the IBAN: that is not a valid one.',
    })
    .optional(),
  opening_balance: amountSchema({ allowZero: true }),
  opening_balance_date: z.string().min(1, 'Pick the date this balance was true.'),
})

type Values = z.input<typeof schema>
type Parsed = z.output<typeof schema>

export function AccountDialog({
  open,
  account,
  onOpenChange,
}: {
  open: boolean
  /** The account being edited, or null when adding one. */
  account: AccountPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const currency = useCurrency()
  const queryClient = useQueryClient()
  const isEdit = account !== null

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      type: AccountType.CURRENT,
      institution: '',
      iban: '',
      opening_balance: '0',
      opening_balance_date: today(),
    },
  })

  useEffect(() => {
    if (!open) return
    form.reset(
      account
        ? {
            name: account.name,
            type: account.type,
            institution: account.institution ?? '',
            iban: account.iban ? formatIban(account.iban) : '',
            opening_balance: String(toMajor(account.opening_balance_minor, account.currency_code)),
            opening_balance_date: account.opening_balance_date,
          }
        : {
            name: '',
            type: AccountType.CURRENT,
            institution: '',
            iban: '',
            opening_balance: '0',
            opening_balance_date: today(),
          },
    )
  }, [open, account, form])

  // Cash is money in a pocket: it sits at no institution, so it is asked for
  // neither. A credit card sits at one, but what it has is a card number, not
  // an IBAN. Hiding a field beats leaving it there to be filled in wrongly.
  const type = form.watch('type')
  const heldAtBank = type !== AccountType.CASH
  const hasIban = heldAtBank && type !== AccountType.CREDIT_CARD

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      if (account) {
        // The opening balance is fixed once set: changing it would rewrite
        // every historical balance, so the API does not accept it here.
        const { error } = await accountsUpdateAccount({
          path: { account_id: account.id },
          body: {
            name: parsed.name,
            type: parsed.type,
            institution: heldAtBank ? parsed.institution || null : null,
            iban: hasIban ? parsed.iban || null : null,
          },
        })
        if (error) throw error
        return
      }

      const { error } = await accountsCreateAccount({
        body: {
          name: parsed.name,
          type: parsed.type,
          institution: heldAtBank ? parsed.institution || null : null,
          iban: hasIban ? parsed.iban || null : null,
          opening_balance_minor: parsed.opening_balance,
          opening_balance_date: parsed.opening_balance_date,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(isEdit ? 'Account saved' : 'Account added')
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${account.name}` : 'Add an account'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'The opening balance cannot change. Record an adjustment transaction instead.'
              : 'Start from the balance the account holds today, or from the day you want to track.'}
          </DialogDescription>
        </DialogHeader>

        <form
          id="account-form"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <Field id="name" label="Name" error={form.formState.errors.name?.message}>
            {(props) => (
              <Input
                {...props}
                {...form.register('name')}
                placeholder="Current account"
                autoFocus
              />
            )}
          </Field>

          <Field id="type" label="Type" error={form.formState.errors.type?.message}>
            {(props) => (
              <Select
                value={type}
                onValueChange={(value) => {
                  form.setValue('type', value as AccountType)
                  // Clear what the form is about to hide. A half typed IBAN
                  // left behind would fail validation the user cannot see.
                  if (value === AccountType.CASH) {
                    form.setValue('institution', '')
                    form.clearErrors('institution')
                  }
                  if (value === AccountType.CASH || value === AccountType.CREDIT_CARD) {
                    form.setValue('iban', '')
                    form.clearErrors('iban')
                  }
                }}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(AccountType).map((type) => (
                    <SelectItem key={type} value={type}>
                      {ACCOUNT_TYPE_LABELS[type]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>

          {heldAtBank ? (
            <>
              <Field
                id="institution"
                label="Bank"
                hint="Optional. Helps tell similar accounts apart."
                error={form.formState.errors.institution?.message}
              >
                {(props) => (
                  <Input {...props} {...form.register('institution')} placeholder="Optional" />
                )}
              </Field>

              {hasIban ? (
                <Field
                  id="iban"
                  label="IBAN"
                  hint="Optional. Listed with a copy button, for when someone has to pay in."
                  error={form.formState.errors.iban?.message}
                >
                  {(props) => (
                    <Input
                      {...props}
                      {...form.register('iban')}
                      placeholder="Optional"
                      autoComplete="off"
                      spellCheck={false}
                    />
                  )}
                </Field>
              ) : null}
            </>
          ) : null}

          {!isEdit ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                id="opening_balance"
                label="Balance today"
                error={form.formState.errors.opening_balance?.message}
              >
                {(props) => (
                  <MoneyInput
                    {...props}
                    {...form.register('opening_balance')}
                    currency={currency}
                  />
                )}
              </Field>

              <Field
                id="opening_balance_date"
                label="As of"
                error={form.formState.errors.opening_balance_date?.message}
              >
                {(props) => (
                  <Input
                    {...props}
                    {...form.register('opening_balance_date')}
                    type="date"
                    max={today()}
                  />
                )}
              </Field>
            </div>
          ) : null}
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="account-form" pending={save.isPending}>
            {isEdit ? 'Save changes' : 'Add account'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
