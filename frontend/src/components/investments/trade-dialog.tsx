import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { AccountType, investmentsCreateTrade, TradeSide } from '@/api'
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
import { useAccounts } from '@/hooks/use-accounts'
import { useHousehold } from '@/hooks/use-household'
import { useInstruments } from '@/hooks/use-instruments'
import { amountSchema } from '@/lib/amount'
import { errorMessage } from '@/lib/api'
import { showIssues } from '@/lib/form'
import { TRADE_SIDE_LABELS } from '@/lib/labels'
import { today } from '@/lib/month'
import { priceSchema, quantitySchema } from '@/lib/quantity'

/**
 * The trade form's shape.
 *
 * The price and the fee are in the instrument's own currency, not the
 * household's, because that is the currency the trade actually happened in.
 * That makes the currency a property of the chosen instrument, so the schema
 * is built once the instrument is known rather than defined at module level.
 */
function buildSchema(currency: string, householdCurrency: string) {
  return z.object({
    instrument_id: z.string().min(1, 'Pick an instrument.'),
    side: z.enum(TradeSide),
    traded_on: z.string().min(1, 'Pick the date it happened.'),
    quantity: quantitySchema(),
    price: priceSchema(currency),
    fee: amountSchema({ currency, allowZero: true }),
    // The cash side is optional: a trade is a fact about a holding whether or
    // not the money is being tracked here. Only the broker is named, because a
    // trade spends cash already sitting there; moving money from a bank to a
    // broker happens on its own day and is an ordinary transfer.
    brokerage_account_id: z.string().optional(),
    // In the household's currency, not the instrument's, because that is what
    // the account is denominated in. Blank means "work it out for me", so an
    // empty string passes through as undefined rather than failing the parse.
    cash_amount: z.union([
      z.literal('').transform(() => undefined),
      amountSchema({ currency: householdCurrency, allowZero: true }),
    ]),
    note: z.string().trim().max(1024).optional(),
  })
}

type Values = z.input<ReturnType<typeof buildSchema>>
type Parsed = z.output<ReturnType<typeof buildSchema>>

export function TradeDialog({
  open,
  instrumentId,
  onOpenChange,
}: {
  open: boolean
  /** The instrument to preselect, when the form was opened from a position. */
  instrumentId: string | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const instruments = useInstruments()
  const accounts = useAccounts()
  const household = useHousehold()

  const defaults: Values = useMemo(
    () => ({
      instrument_id: instrumentId ?? '',
      side: TradeSide.BUY,
      traded_on: today(),
      quantity: '',
      price: '',
      fee: '0',
      brokerage_account_id: '',
      cash_amount: '',
      note: '',
    }),
    [instrumentId],
  )

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(buildSchema('EUR', 'EUR')),
    defaultValues: defaults,
  })

  const selectedId = form.watch('instrument_id')
  const selected = instruments.data?.data.find((one) => one.id === selectedId)
  const currency = selected?.currency_code ?? 'EUR'
  // The accounts are in the household's currency, never the listing's, so
  // the cash figure is entered and shown in that one.
  const householdCurrency = household.data?.currency_code ?? 'EUR'
  // A trade spends or receives cash that is already with a broker, so only
  // brokerage accounts are offered.
  const brokerageAccounts = (accounts.data?.data ?? []).filter(
    (one) => one.type === AccountType.BROKERAGE,
  )
  // Which way the money goes, so the label says what is happening rather than
  // making the reader work it out from the direction field above.
  const isBuy = form.watch('side') === TradeSide.BUY

  useEffect(() => {
    if (open) form.reset(defaults)
  }, [open, defaults, form])

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      const { error } = await investmentsCreateTrade({
        body: {
          instrument_id: parsed.instrument_id,
          side: parsed.side,
          traded_on: parsed.traded_on,
          quantity_micro: parsed.quantity,
          price_micro: parsed.price,
          fee_minor: parsed.fee,
          brokerage_account_id: parsed.brokerage_account_id || null,
          // Sent only when it was typed. Left out, the backend works it out
          // from the trade, which is exact in one currency and a conversion at
          // the latest stored rate otherwise.
          cash_amount_minor:
            parsed.brokerage_account_id && parsed.cash_amount !== undefined
              ? parsed.cash_amount
              : null,
          note: parsed.note || null,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
      void queryClient.invalidateQueries({ queryKey: ['trades'] })
      // The cash side moves an account balance, so anything showing one is now
      // out of date: the accounts page, and the dashboard's net worth.
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
      void queryClient.invalidateQueries({ queryKey: ['reports'] })
      toast.success('Trade recorded')
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Wider than the app's usual form dialog. This one pairs fields two
          across on three rows, and the instrument picker holds a symbol and a
          full fund name on one line, which the narrower width truncates. */}
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Record a trade</DialogTitle>
          <DialogDescription>
            The price and the fee are in the instrument's own currency, as your broker showed them.
          </DialogDescription>
        </DialogHeader>

        <form
          id="trade-form"
          // Re-parsed against the chosen instrument's currency, so a price in
          // a zero-decimal currency is not quietly given cents.
          onSubmit={form.handleSubmit(() => {
            const parsed = buildSchema(currency, householdCurrency).safeParse(form.getValues())
            if (parsed.success) {
              save.mutate(parsed.data)
              return
            }
            // The resolver validated against a placeholder currency, so this
            // second parse can fail where the first passed. Its complaints have
            // to reach the fields, or the button just looks dead.
            showIssues(form, parsed.error)
          })}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <Field
            id="instrument_id"
            label="Instrument"
            error={form.formState.errors.instrument_id?.message}
          >
            {(props) => (
              <Select
                value={selectedId}
                onValueChange={(value) => form.setValue('instrument_id', value)}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue placeholder="Pick one" />
                </SelectTrigger>
                {/* Anchored below the field rather than over it. The default
                    places the chosen option on top of the trigger, which with
                    a placeholder and long fund names lands the list across the
                    field it belongs to. */}
                <SelectContent position="popper" align="start">
                  {instruments.data?.data.map((one) => (
                    <SelectItem key={one.id} value={one.id}>
                      {one.symbol} · {one.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="side" label="Direction" error={form.formState.errors.side?.message}>
              {(props) => (
                <Select
                  value={form.watch('side')}
                  onValueChange={(value) => form.setValue('side', value as TradeSide)}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent position="popper" align="start">
                    {Object.values(TradeSide).map((side) => (
                      <SelectItem key={side} value={side}>
                        {TRADE_SIDE_LABELS[side]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>

            <Field id="traded_on" label="Date" error={form.formState.errors.traded_on?.message}>
              {(props) => (
                <Input {...props} {...form.register('traded_on')} type="date" max={today()} />
              )}
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="quantity"
              label="Units"
              hint="Fractions are fine."
              error={form.formState.errors.quantity?.message}
            >
              {(props) => (
                <Input
                  {...props}
                  {...form.register('quantity')}
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="10"
                  className="text-right tabular-nums"
                />
              )}
            </Field>

            <Field id="price" label="Price per unit" error={form.formState.errors.price?.message}>
              {(props) => (
                <MoneyInput
                  {...props}
                  {...form.register('price')}
                  currency={currency}
                  placeholder="128.4567"
                />
              )}
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="brokerage_account_id"
              label={isBuy ? 'Bought through' : 'Sold through'}
              hint={
                brokerageAccounts.length === 0
                  ? 'Add a brokerage account first, on the Accounts page.'
                  : 'Optional. Leave blank to record the holding only.'
              }
              error={form.formState.errors.brokerage_account_id?.message}
            >
              {(props) => (
                <Select
                  value={form.watch('brokerage_account_id') || 'none'}
                  onValueChange={(value) =>
                    form.setValue('brokerage_account_id', value === 'none' ? '' : value)
                  }
                  disabled={brokerageAccounts.length === 0}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent position="popper" align="start">
                    <SelectItem value="none">No account</SelectItem>
                    {brokerageAccounts.map((one) => (
                      <SelectItem key={one.id} value={one.id}>
                        {one.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>

            <Field
              id="cash_amount"
              label="Cash moved"
              hint={
                selected && selected.currency_code !== householdCurrency
                  ? `In ${householdCurrency}. Blank converts at the stored rate, which is not your bank's.`
                  : 'Blank works it out from the trade.'
              }
              error={form.formState.errors.cash_amount?.message}
            >
              {(props) => (
                <MoneyInput
                  {...props}
                  {...form.register('cash_amount')}
                  currency={householdCurrency}
                  placeholder="Auto"
                  disabled={!form.watch('brokerage_account_id')}
                />
              )}
            </Field>
          </div>

          <Field
            id="fee"
            label="Fees"
            hint="Commission and taxes. Part of what the units cost."
            error={form.formState.errors.fee?.message}
          >
            {(props) => <MoneyInput {...props} {...form.register('fee')} currency={currency} />}
          </Field>

          <Field
            id="note"
            label="Note"
            hint="Optional."
            error={form.formState.errors.note?.message}
          >
            {(props) => <Input {...props} {...form.register('note')} placeholder="Optional" />}
          </Field>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="trade-form" pending={save.isPending}>
            Record trade
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
