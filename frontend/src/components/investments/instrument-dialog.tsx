import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  InstrumentKind,
  investmentsCreateInstrument,
  investmentsSearchSymbols,
  investmentsUpdateInstrument,
  type InstrumentPublic,
} from '@/api'
import { Field, FormError } from '@/components/form-field'
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
import { errorMessage } from '@/lib/api'
import { refill } from '@/lib/form'
import { INSTRUMENT_KIND_LABELS } from '@/lib/labels'

const schema = z.object({
  symbol: z.string().trim().min(1, 'Enter the ticker symbol.').max(32),
  name: z.string().trim().min(1, 'Give it a name.').max(255),
  kind: z.enum(InstrumentKind),
  exchange: z.string().trim().max(64).optional(),
  // Left blank on purpose in the common case. The server asks the market data
  // provider what the listing quotes in, which is the only place that answer
  // is certain. Filling it in is how something nobody quotes gets tracked.
  currency_code: z
    .string()
    .trim()
    .toUpperCase()
    .regex(/^([A-Z]{3})?$/, 'Use a three letter code, such as EUR.')
    .optional(),
})

type Values = z.input<typeof schema>
type Parsed = z.output<typeof schema>

/** Stands in for the instrument's id while the dialog is adding one. */
const NEW_INSTRUMENT = 'new'

const EMPTY: Values = {
  symbol: '',
  name: '',
  kind: InstrumentKind.ETF,
  exchange: '',
  currency_code: '',
}

export function InstrumentDialog({
  open,
  instrument,
  onOpenChange,
}: {
  open: boolean
  /** The instrument being edited, or null when adding one. */
  instrument: InstrumentPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const isEdit = instrument !== null
  const [query, setQuery] = useState('')
  // What is actually searched for, which lags what is typed. The provider
  // charges one API call per search out of twenty a day, so typing "vuaa" must
  // cost one search rather than three.
  const [debouncedQuery, setDebouncedQuery] = useState('')
  // Clearing the box takes effect at once, so a list the reader has just
  // emptied never lingers for another 400ms. Read off the box rather than
  // written to state from an effect, which would render the dialog twice with
  // the stale matches still under it.
  const settledQuery = query === '' ? '' : debouncedQuery

  // The search box belongs to this opening of the dialog, not to the last one:
  // a ticker typed and abandoned is not what the next instrument starts from.
  const [searchedFor, setSearchedFor] = useState<string | null>(null)
  const opening = open ? (instrument?.id ?? NEW_INSTRUMENT) : null
  if (opening !== searchedFor) {
    setSearchedFor(opening)
    setQuery('')
  }

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(schema),
    defaultValues: EMPTY,
  })

  // Watched through `useWatch()` rather than the form's own `watch()`, which
  // hands back a function React Compiler will not memoize and skips the whole
  // component over.
  const kind = useWatch({ control: form.control, name: 'kind' })

  useEffect(() => {
    if (!open) return
    refill(
      form,
      instrument
        ? {
            symbol: instrument.symbol,
            name: instrument.name,
            kind: instrument.kind,
            exchange: instrument.exchange ?? '',
            currency_code: instrument.currency_code,
          }
        : EMPTY,
    )
  }, [open, instrument, form])

  // Nothing is searched for until the typing has paused.
  useEffect(() => {
    if (query === '') return

    const timer = setTimeout(() => setDebouncedQuery(query), 400)
    return () => clearTimeout(timer)
  }, [query])

  // Only runs once the box holds enough to be a search rather than a keystroke.
  const matches = useQuery({
    queryKey: ['symbols', settledQuery],
    enabled: open && !isEdit && settledQuery.trim().length >= 2,
    queryFn: async () => {
      const { data, error } = await investmentsSearchSymbols({ query: { q: settledQuery.trim() } })
      if (error) throw error
      return data
    },
    // Held for an hour rather than five minutes: a listing's name and currency
    // do not move, and a repeated search is a wasted API call.
    staleTime: 60 * 60_000,
    retry: false,
  })

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      if (instrument) {
        const { error } = await investmentsUpdateInstrument({
          path: { instrument_id: instrument.id },
          body: {
            name: parsed.name,
            kind: parsed.kind,
            exchange: parsed.exchange || null,
          },
        })
        if (error) throw error
        return
      }

      const { error } = await investmentsCreateInstrument({
        body: {
          symbol: parsed.symbol,
          name: parsed.name,
          kind: parsed.kind,
          exchange: parsed.exchange || null,
          currency_code: parsed.currency_code || null,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['instruments'] })
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
      toast.success(isEdit ? 'Instrument saved' : 'Instrument added')
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${instrument.symbol}` : 'Track an instrument'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'The symbol and the currency cannot change: every stored price and trade was measured against them.'
              : 'Search for it, or type the ticker as your exchange lists it, suffix included.'}
          </DialogDescription>
        </DialogHeader>

        {!isEdit ? (
          <div className="space-y-2">
            <div className="relative">
              <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by name, e.g. All-World"
                className="pl-9"
                autoFocus
              />
            </div>

            {matches.isError ? (
              <p className="text-muted-foreground text-xs">
                Search is unavailable right now. Type the ticker below instead.
              </p>
            ) : matches.data && matches.data.count > 0 ? (
              <div className="max-h-40 divide-y overflow-y-auto rounded-md border">
                {matches.data.data.map((match) => (
                  <button
                    key={match.symbol}
                    type="button"
                    className="hover:bg-accent flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left"
                    onClick={() => {
                      form.setValue('symbol', match.symbol)
                      form.setValue('name', match.name)
                      form.setValue('kind', match.kind ?? InstrumentKind.OTHER)
                      form.setValue('exchange', match.exchange ?? '')
                      // The search already reported what the listing quotes in,
                      // so carrying it over means saving costs no further
                      // lookup. The provider bills one call per holding out of
                      // twenty a day, and this is one of them.
                      if (match.currency_code) form.setValue('currency_code', match.currency_code)
                      setQuery('')
                    }}
                  >
                    <span className="text-sm font-medium">{match.symbol}</span>
                    <span className="text-muted-foreground line-clamp-1 text-xs">
                      {match.name}
                      {match.exchange ? ` · ${match.exchange}` : ''}
                    </span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        <form
          id="instrument-form"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="symbol" label="Symbol" error={form.formState.errors.symbol?.message}>
              {(props) => (
                <Input
                  {...props}
                  {...form.register('symbol')}
                  placeholder="VWCE.DE"
                  disabled={isEdit}
                  className="uppercase"
                />
              )}
            </Field>

            <Field id="kind" label="Type" error={form.formState.errors.kind?.message}>
              {(props) => (
                <Select
                  value={kind}
                  onValueChange={(value) => form.setValue('kind', value as InstrumentKind)}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.values(InstrumentKind).map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {INSTRUMENT_KIND_LABELS[kind]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          </div>

          <Field id="name" label="Name" error={form.formState.errors.name?.message}>
            {(props) => (
              <Input {...props} {...form.register('name')} placeholder="Vanguard FTSE All-World" />
            )}
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="exchange"
              label="Exchange"
              hint="Optional."
              error={form.formState.errors.exchange?.message}
            >
              {(props) => <Input {...props} {...form.register('exchange')} placeholder="XETRA" />}
            </Field>

            <Field
              id="currency_code"
              label="Currency"
              hint={isEdit ? 'Fixed once set.' : 'Filled in by the search. Blank means look it up.'}
              error={form.formState.errors.currency_code?.message}
            >
              {(props) => (
                <Input
                  {...props}
                  {...form.register('currency_code')}
                  placeholder="Auto"
                  disabled={isEdit}
                  maxLength={3}
                  className="uppercase"
                />
              )}
            </Field>
          </div>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="instrument-form" pending={save.isPending}>
            {isEdit ? 'Save changes' : 'Track it'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
