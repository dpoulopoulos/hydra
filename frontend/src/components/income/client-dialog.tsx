import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  CategoryKind,
  incomeCreateClient,
  incomeUpdateClient,
  type IncomeClientPublic,
} from '@/api'
import { Field, FormError } from '@/components/form-field'
import { FormSection } from '@/components/form-section'
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
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import { useAccounts } from '@/hooks/use-accounts'
import { useCategories } from '@/hooks/use-categories'
import { useCurrency } from '@/hooks/use-household'
import { useDecrypted, useVault } from '@/hooks/use-vault'
import { amountSchema } from '@/lib/amount'
import { WeekdayPicker } from '@/components/income/weekday-picker'
import { AD_HOC, CADENCE_PRESETS, describeCadence, isWeekly, presetOf } from '@/lib/cadence'
import { errorMessage } from '@/lib/api'
import { formatMoney, toMajor, toMinor } from '@/lib/money'
import { formatDate, today } from '@/lib/month'

function buildSchema(currency: string) {
  return z.object({
    name: z.string().trim().min(1, 'Give this person a name you will recognise.').max(120),
    rate: amountSchema({ currency, allowZero: true }),
    default_account_id: z.string().min(1, 'Pick where the money lands.'),
    // Optional, so a practice that does not file income by category is not
    // forced to invent one.
    default_category_id: z.string().optional(),
    // How often you see them, as one of the presets. "No set pattern" is a
    // real answer, not a missing one.
    cadence: z.string().min(1),
    // What the pattern is pinned to: a weekly one keeps this weekday for ever.
    cadence_anchor_on: z.string().optional(),
    // Empty is a real answer: the pattern then keeps the weekday it was
    // pinned to, which is what one appointment a week means.
    cadence_weekdays: z.array(z.number().int().min(0).max(6)),
    note: z.string().trim().max(500).optional(),
  })
}

type Values = z.input<ReturnType<typeof buildSchema>>
type Parsed = z.output<ReturnType<typeof buildSchema>>

/**
 * Add or edit a client.
 *
 * The name and the note are encrypted here, in the browser, before anything is
 * sent. That is why the dialog refuses to open while the vault is locked:
 * without the key there is nothing to encrypt with.
 */
export function ClientDialog({
  open,
  client,
  onOpenChange,
}: {
  open: boolean
  /** The client to edit, or null to add a new one. */
  client: IncomeClientPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const queryClient = useQueryClient()
  const currency = useCurrency()
  const accounts = useAccounts()
  const categories = useCategories({ kind: CategoryKind.INCOME })
  const { encrypt } = useVault()
  const existingName = useDecrypted(client?.name_ct)
  const existingNote = useDecrypted(client?.note_ct)
  // There is a stored note, and this device cannot read it: the decrypt has
  // not landed yet, or it failed. Either way the field is showing empty for a
  // reason that has nothing to do with what the reader wants, so an empty
  // field must not be taken as "delete it".
  const noteIsUnreadable = client?.note_ct != null && existingNote === null

  const defaults: Values = useMemo(
    () => ({
      name: existingName ?? '',
      rate: client ? String(toMajor(client.default_rate_minor, currency)) : '',
      default_account_id: client?.default_account_id ?? '',
      default_category_id: client?.default_category_id ?? '',
      cadence: presetOf(client?.cadence_frequency, client?.cadence_interval ?? 1),
      cadence_anchor_on: client?.cadence_anchor_on ?? today(),
      cadence_weekdays: client?.cadence_weekdays ?? [],
      note: existingNote ?? '',
    }),
    [client, currency, existingName, existingNote],
  )

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(buildSchema(currency)),
    defaultValues: defaults,
  })

  // The name arrives from an asynchronous decrypt, so the form is refilled when
  // it lands rather than only when the dialog opens.
  useEffect(() => {
    if (open) form.reset(defaults)
  }, [open, defaults, form])

  const save = useMutation({
    mutationFn: async (parsed: Parsed) => {
      const preset = CADENCE_PRESETS.find((one) => one.value === parsed.cadence)
      const body = {
        name_ct: await encrypt(parsed.name),
        note_ct: parsed.note
          ? await encrypt(parsed.note)
          : // Left as it was found, rather than cleared by a blank the reader
            // never actually typed.
            noteIsUnreadable
            ? client.note_ct
            : null,
        default_rate_minor: parsed.rate,
        default_account_id: parsed.default_account_id,
        default_category_id: parsed.default_category_id || null,
        cadence_frequency: preset?.frequency ?? null,
        cadence_interval: preset?.interval ?? 1,
        // Sent only alongside a frequency. The API refuses half a schedule,
        // because "every week" says nothing without a day to pin it to.
        cadence_anchor_on: preset?.frequency ? (parsed.cadence_anchor_on ?? today()) : null,
        // Only a weekly pattern can carry days; the API refuses them
        // elsewhere rather than storing something that never applies.
        cadence_weekdays: isWeekly(preset?.frequency) ? parsed.cadence_weekdays : [],
      }

      const { error } = client
        ? await incomeUpdateClient({ path: { client_id: client.id }, body })
        : await incomeCreateClient({ body })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['income-clients'] })
      void queryClient.invalidateQueries({ queryKey: ['income-forecast'] })
      toast.success(client ? 'Client saved' : 'Client added')
      onOpenChange(false)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const preset = CADENCE_PRESETS.find((one) => one.value === form.watch('cadence'))
  const openAccounts = (accounts.data?.data ?? []).filter((one) => one.archived_at === null)

  // What the form currently says, in one sentence. The same device the
  // recurring rule dialog uses: a schedule assembled from four controls is
  // hard to picture until something reads it back.
  const anchor = form.watch('cadence_anchor_on')
  // The field holds whatever has been typed so far, so the fee is only shown
  // back once it reads as a number. A half-typed "4" is not worth echoing.
  const typedRate = Number(String(form.watch('rate') ?? '').replace(',', '.'))
  const rateLabel =
    Number.isFinite(typedRate) && typedRate > 0
      ? `, ${formatMoney(toMinor(typedRate, currency), currency)} a session`
      : ''

  const schedule = preset?.frequency
    ? `${describeCadence(preset.frequency, preset.interval, anchor, form.watch('cadence_weekdays'))}${
        anchor ? `, from ${formatDate(anchor)}` : ''
      }`
    : 'Seen as and when'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* Wide enough to pair the fields two across, and scrolling inside
          itself so the title and the buttons stay put on a short screen. */}
      <DialogContent className="grid-rows-[auto_minmax(0,1fr)_auto] gap-5 sm:max-w-2xl sm:p-6">
        <DialogHeader>
          <DialogTitle>{client ? 'Edit client' : 'Add a client'}</DialogTitle>
          <DialogDescription>
            Their name and note are scrambled on this device. The server never sees either.
          </DialogDescription>
        </DialogHeader>

        <form
          id="client-form"
          onSubmit={form.handleSubmit((parsed) => save.mutate(parsed))}
          className="-mx-1 space-y-6 overflow-y-auto px-1"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <FormSection title="Who they are">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="name" label="Name" error={form.formState.errors.name?.message}>
                {(props) => <Input autoComplete="off" {...props} {...form.register('name')} />}
              </Field>

              <Field
                id="rate"
                label="Usual fee"
                hint="A starting point. Any session can differ."
                error={form.formState.errors.rate?.message}
              >
                {(props) => (
                  <MoneyInput currency={currency} {...props} {...form.register('rate')} />
                )}
              </Field>
            </div>

            <Field id="note" label="Note" error={form.formState.errors.note?.message}>
              {(props) => (
                <Textarea rows={2} placeholder="Optional" {...props} {...form.register('note')} />
              )}
            </Field>
          </FormSection>

          <Separator />

          <FormSection title="When you see them">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id="cadence" label="How often" error={form.formState.errors.cadence?.message}>
                {(props) => (
                  <Select
                    value={form.watch('cadence')}
                    onValueChange={(value) =>
                      form.setValue('cadence', value, { shouldDirty: true })
                    }
                  >
                    <SelectTrigger className="w-full" {...props}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent position="popper" align="start">
                      {CADENCE_PRESETS.map((one) => (
                        <SelectItem key={one.value} value={one.value}>
                          {one.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </Field>

              {form.watch('cadence') !== AD_HOC ? (
                <Field
                  id="cadence_anchor_on"
                  label="Starting from"
                  error={form.formState.errors.cadence_anchor_on?.message}
                >
                  {(props) => (
                    <Input type="date" {...props} {...form.register('cadence_anchor_on')} />
                  )}
                </Field>
              ) : null}
            </div>

            {isWeekly(preset?.frequency) ? (
              <Field
                id="cadence_weekdays"
                label="Which days"
                hint="Pick none to keep the day it starts on."
                error={form.formState.errors.cadence_weekdays?.message}
              >
                {(props) => (
                  <WeekdayPicker
                    id={props.id}
                    value={form.watch('cadence_weekdays')}
                    onChange={(value) =>
                      form.setValue('cadence_weekdays', value, { shouldDirty: true })
                    }
                  />
                )}
              </Field>
            ) : null}
          </FormSection>

          <Separator />

          <FormSection title="Where the money goes">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                id="default_account_id"
                label="Lands in"
                error={form.formState.errors.default_account_id?.message}
              >
                {(props) => (
                  <Select
                    value={form.watch('default_account_id')}
                    onValueChange={(value) =>
                      form.setValue('default_account_id', value, { shouldDirty: true })
                    }
                  >
                    <SelectTrigger className="w-full" {...props}>
                      <SelectValue placeholder="Pick an account" />
                    </SelectTrigger>
                    <SelectContent position="popper" align="start">
                      {openAccounts.map((account) => (
                        <SelectItem key={account.id} value={account.id}>
                          {account.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </Field>

              <Field
                id="default_category_id"
                label="Filed under"
                error={form.formState.errors.default_category_id?.message}
              >
                {(props) => (
                  <Select
                    value={form.watch('default_category_id') || 'none'}
                    onValueChange={(value) =>
                      form.setValue('default_category_id', value === 'none' ? '' : value, {
                        shouldDirty: true,
                      })
                    }
                  >
                    <SelectTrigger className="w-full" {...props}>
                      <SelectValue placeholder="No category" />
                    </SelectTrigger>
                    <SelectContent position="popper" align="start">
                      <SelectItem value="none">No category</SelectItem>
                      {(categories.data?.data ?? []).map((category) => (
                        <SelectItem key={category.id} value={category.id}>
                          {category.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </Field>
            </div>
          </FormSection>

          <p className="bg-muted text-muted-foreground rounded-lg px-3 py-2 text-sm">
            {schedule}
            {rateLabel}.
          </p>
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="client-form" pending={save.isPending}>
            {client ? 'Save changes' : 'Add client'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
