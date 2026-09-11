import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { investmentsSetInstrumentPrice, type InstrumentPublic } from '@/api'
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
import { errorMessage } from '@/lib/api'
import { refill, showIssues } from '@/lib/form'
import { useLocale } from '@/lib/locale-context'
import { formatPrice, formatPriceInput, priceSchema } from '@/lib/quantity'

/**
 * The price is in the instrument's own currency, never the household's. A
 * listing quotes in what its exchange says, and typing a converted number here
 * would be converted a second time on the way to the portfolio.
 */
function buildSchema(currency: string, locale: string | undefined) {
  return z.object({ price: priceSchema(currency, { locale }) })
}

type Values = z.input<ReturnType<typeof buildSchema>>
type Parsed = z.output<ReturnType<typeof buildSchema>>

/**
 * Type in what one unit is worth.
 *
 * The escape hatch for the one part of this app that can refuse. The price
 * provider bills per holding out of a small daily allowance, can be switched
 * off, and does not carry every listing. None of that should stop someone
 * recording a number they are looking straight at.
 */
export function PriceDialog({
  open,
  instrument,
  onOpenChange,
}: {
  open: boolean
  /** The instrument being priced, or null when the dialog is closed. */
  instrument: InstrumentPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const currency = instrument?.currency_code ?? 'EUR'
  const locale = useLocale()

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(buildSchema(currency, locale)),
    defaultValues: { price: '' },
  })

  useEffect(() => {
    if (!open || !instrument) return
    // Seeded with the price already on the row, so correcting a figure does not
    // mean retyping it, and written with the separator the household's locale
    // reads back as a decimal point. Blank when there has never been one.
    refill(form, {
      price:
        instrument.last_price_micro === null || instrument.last_price_micro === undefined
          ? ''
          : formatPriceInput(instrument.last_price_micro, instrument.currency_code, locale),
    })
  }, [open, instrument, locale, form])

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      if (!instrument) return
      const { error } = await investmentsSetInstrumentPrice({
        path: { instrument_id: instrument.id },
        body: { price_micro: parsed.price },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
      void queryClient.invalidateQueries({ queryKey: ['instruments'] })
      toast.success(`${instrument?.symbol} priced`)
      onOpenChange(false)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Set the price of {instrument?.symbol}</DialogTitle>
          <DialogDescription>
            What one unit is worth, in {currency}. Use this when the provider has run out of calls
            for the day, or does not carry this listing.
          </DialogDescription>
        </DialogHeader>

        <form
          id="price-form"
          // Re-parsed against the instrument's own currency, so a price in a
          // zero-decimal currency is not quietly given cents.
          onSubmit={form.handleSubmit(() => {
            const parsed = buildSchema(currency, locale).safeParse(form.getValues())
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
            id="price"
            label="Price per unit"
            hint={
              instrument?.last_price_micro === null || instrument?.last_price_micro === undefined
                ? 'No price recorded yet.'
                : `Currently ${formatPrice(instrument.last_price_micro, currency, locale)}${
                    instrument.last_price_is_manual ? ', typed in' : ', from the provider'
                  }.`
            }
            error={form.formState.errors.price?.message}
          >
            {(props) => (
              <MoneyInput
                {...props}
                {...form.register('price')}
                currency={currency}
                placeholder="128.4567"
              />
            )}
          </Field>

          <p className="text-muted-foreground text-xs">
            A typed price is used exactly like a fetched one, and is marked so you can tell them
            apart. It also counts as current, so refreshing will not spend a call replacing it until
            the cache window passes.
          </p>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="price-form" pending={save.isPending}>
            Save price
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
