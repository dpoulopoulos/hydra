import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  incomeCreateSession,
  incomeUpdateSession,
  IncomeSessionStatus,
  PaymentStatus,
  type IncomeSessionPublic,
} from '@/api'
import { ClientName } from '@/components/income/client-name'
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
import { useCurrency } from '@/hooks/use-household'
import { useIncomeClients } from '@/hooks/use-income-clients'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { PAYMENT_STATUS_LABELS, SESSION_STATUS_LABELS } from '@/lib/labels'
import { toMajor } from '@/lib/money'
import { today } from '@/lib/month'

function buildSchema(currency: string) {
  return z.object({
    client_id: z.string().min(1, 'Pick who this was with.'),
    occurs_on: z.string().min(1, 'Pick the day.'),
    fee: amountSchema(currency, { allowZero: true }),
    status: z.enum(IncomeSessionStatus),
    payment_status: z.enum(PaymentStatus),
    paid_on: z.string().optional(),
  })
}

type Values = z.input<ReturnType<typeof buildSchema>>
type Parsed = z.output<ReturnType<typeof buildSchema>>

/**
 * What usually happened to the money, given what happened to the hour.
 *
 * Most sessions are paid on the day, and most missed ones are not charged, so
 * changing the outcome moves the payment to match. It is a starting point and
 * one click undoes it: a client who says "next week" goes back to unpaid, and
 * a late cancellation fee goes back to paid.
 */
function usualPayment(status: IncomeSessionStatus): PaymentStatus {
  if (status === IncomeSessionStatus.ATTENDED) return PaymentStatus.PAID
  if (status === IncomeSessionStatus.SCHEDULED) return PaymentStatus.PENDING
  return PaymentStatus.WAIVED
}

export function SessionDialog({
  open,
  session,
  clientId,
  onOpenChange,
}: {
  open: boolean
  /** The session to edit, or null to record a new one. */
  session: IncomeSessionPublic | null
  /** A client to preselect, when opened from that client's row. */
  clientId?: string | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const currency = useCurrency()
  // Archived ones included, so editing a session with somebody who has since
  // stopped coming shows their name rather than the placeholder. They are not
  // offered for a new session, though: you do not book somebody who has left.
  const clients = useIncomeClients(true)

  const defaults: Values = useMemo(
    () => ({
      client_id: session?.client_id ?? clientId ?? '',
      occurs_on: session?.occurs_on ?? today(),
      fee: session ? String(toMajor(session.fee_minor, currency)) : '',
      status: session?.status ?? IncomeSessionStatus.ATTENDED,
      payment_status: session?.payment_status ?? PaymentStatus.PAID,
      paid_on: session?.paid_on ?? '',
    }),
    [session, clientId, currency],
  )

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(buildSchema(currency)),
    defaultValues: defaults,
  })

  useEffect(() => {
    if (open) form.reset(defaults)
  }, [open, defaults, form])

  const selectedClientId = form.watch('client_id')
  const status = form.watch('status')
  const paymentStatus = form.watch('payment_status')
  const selectedClient = clients.data?.data.find((one) => one.id === selectedClientId)
  const pickable = (clients.data?.data ?? []).filter(
    (one) => one.archived_at === null || one.id === selectedClientId,
  )

  // The fee is prefilled from the client's usual rate but stays editable: fees
  // varying from session to session is the reason this whole page exists.
  useEffect(() => {
    if (!selectedClient || form.formState.dirtyFields.fee || session) return
    form.setValue('fee', String(toMajor(selectedClient.default_rate_minor, currency)))
  }, [selectedClient, currency, form, session])

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      const isPaid = parsed.payment_status === PaymentStatus.PAID
      const body = {
        occurs_on: parsed.occurs_on,
        fee_minor: parsed.fee,
        status: parsed.status,
        payment_status: parsed.payment_status,
        // The ledger is dated when the money moved, so an unpaid session
        // cannot carry a date and a paid one falls back to the day of the hour.
        paid_on: isPaid ? parsed.paid_on || parsed.occurs_on : null,
      }

      const { error } = session
        ? await incomeUpdateSession({
            path: { session_id: session.id },
            body: { ...body, client_id: parsed.client_id },
          })
        : await incomeCreateSession({ body: { ...body, client_id: parsed.client_id } })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['income-sessions'] })
      void queryClient.invalidateQueries({ queryKey: ['income-summary'] })
      void queryClient.invalidateQueries({ queryKey: ['income-forecast'] })
      // A paid session writes to the ledger and moves an account balance, so
      // anything showing either of those is now out of date.
      void queryClient.invalidateQueries({ queryKey: ['transactions'] })
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success(session ? 'Session saved' : 'Session recorded')
      onOpenChange(false)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{session ? 'Edit session' : 'Log a session'}</DialogTitle>
          <DialogDescription>
            A session only counts as income once it has been paid. Until then it sits in what you
            are owed.
          </DialogDescription>
        </DialogHeader>

        <form
          id="session-form"
          onSubmit={form.handleSubmit((parsed) => save.mutate(parsed))}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <Field id="client_id" label="Client" error={form.formState.errors.client_id?.message}>
            {(props) => (
              <Select
                value={selectedClientId}
                onValueChange={(value) => form.setValue('client_id', value, { shouldDirty: true })}
              >
                <SelectTrigger className="w-full" {...props}>
                  <SelectValue placeholder="Pick a client" />
                </SelectTrigger>
                {/* Anchored below the field rather than over it. The default
                    places the chosen option on top of the trigger, which with a
                    placeholder and a list of names lands the list across the
                    field it belongs to. */}
                <SelectContent position="popper" align="start">
                  {pickable.map((one) => (
                    <SelectItem key={one.id} value={one.id}>
                      <ClientName nameCt={one.name_ct} ownerUserId={one.owner_user_id} />
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="occurs_on"
              label="Day of the session"
              error={form.formState.errors.occurs_on?.message}
            >
              {(props) => <Input type="date" {...props} {...form.register('occurs_on')} />}
            </Field>

            <Field id="fee" label="Fee" error={form.formState.errors.fee?.message}>
              {(props) => <MoneyInput currency={currency} {...props} {...form.register('fee')} />}
            </Field>
          </div>

          <Field id="status" label="What happened">
            {() => (
              <Tabs
                value={status}
                onValueChange={(value) => {
                  const next = value as IncomeSessionStatus
                  form.setValue('status', next, { shouldDirty: true })
                  // Only while the payment has not been touched, so an edit
                  // that fixes the outcome does not silently rewrite the money.
                  if (!form.formState.dirtyFields.payment_status) {
                    form.setValue('payment_status', usualPayment(next))
                  }
                }}
              >
                <TabsList className="w-full">
                  {Object.values(IncomeSessionStatus).map((value) => (
                    <TabsTrigger key={value} value={value} className="flex-1">
                      {SESSION_STATUS_LABELS[value]}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            )}
          </Field>

          <Field id="payment_status" label="The money">
            {() => (
              <Tabs
                value={paymentStatus}
                onValueChange={(value) =>
                  form.setValue('payment_status', value as PaymentStatus, { shouldDirty: true })
                }
              >
                <TabsList className="w-full">
                  {Object.values(PaymentStatus).map((value) => (
                    <TabsTrigger key={value} value={value} className="flex-1">
                      {PAYMENT_STATUS_LABELS[value]}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            )}
          </Field>

          {paymentStatus === PaymentStatus.PAID ? (
            <Field
              id="paid_on"
              label="Day the money arrived"
              hint="Usually the same day. If they paid later, this is the date the ledger uses."
              error={form.formState.errors.paid_on?.message}
            >
              {(props) => <Input type="date" {...props} {...form.register('paid_on')} />}
            </Field>
          ) : null}
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="session-form" pending={save.isPending}>
            {session ? 'Save' : 'Log session'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
