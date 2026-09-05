import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Field, FormError } from '@/components/form-field'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { useVault } from '@/hooks/use-vault'
import { MIN_PIN_LENGTH } from '@/lib/income-vault'

/** What the dialog is being opened for. All three ask for a PIN. */
export type PinMode = 'set-up' | 'unlock' | 'change'

const unlockSchema = z.object({
  pin: z.string().min(1, 'Enter your PIN.'),
  confirm: z.string().optional(),
})

const createSchema = z
  .object({
    pin: z.string().min(MIN_PIN_LENGTH, `Use at least ${MIN_PIN_LENGTH} characters.`),
    confirm: z.string().min(1, 'Type it again.'),
  })
  // Typed twice, because a PIN nobody can remember loses every name behind it
  // and there is no reset that keeps them.
  .refine((values) => values.pin === values.confirm, {
    message: 'The two do not match.',
    path: ['confirm'],
  })

type Values = { pin: string; confirm?: string }

const COPY: Record<PinMode, { title: string; description: string; action: string }> = {
  'set-up': {
    title: 'Choose a PIN for client names',
    description:
      'Names are encrypted in this browser. The server only ever stores the scrambled version.',
    action: 'Set the PIN',
  },
  unlock: {
    title: 'Unlock client names',
    description:
      'Your PIN stays on this device. Names lock again after fifteen minutes without use, and whenever you reload the page.',
    action: 'Unlock',
  },
  change: {
    title: 'Change the PIN',
    description: 'Every name stays readable. Only the lock on them changes.',
    action: 'Change the PIN',
  },
}

/**
 * Ask for the PIN that protects the client names.
 *
 * One dialog for all three jobs, because they ask the same question and only
 * differ in what is done with the answer.
 */
export function PinDialog({
  open,
  mode,
  onOpenChange,
}: {
  open: boolean
  mode: PinMode
  onOpenChange: (open: boolean) => void
}) {
  const vault = useVault()
  const needsConfirmation = mode !== 'unlock'
  const copy = COPY[mode]

  const form = useForm<Values>({
    resolver: zodResolver(needsConfirmation ? createSchema : unlockSchema),
    defaultValues: { pin: '', confirm: '' },
  })

  useEffect(() => {
    if (open) form.reset({ pin: '', confirm: '' })
  }, [open, form])

  const submit = form.handleSubmit(async (values) => {
    try {
      if (mode === 'set-up') await vault.setUp(values.pin)
      else if (mode === 'unlock') await vault.unlock(values.pin)
      else await vault.changePin(values.pin)

      toast.success(mode === 'unlock' ? 'Names unlocked' : 'PIN saved')
      onOpenChange(false)
    } catch (error) {
      // A wrong PIN is an unwrap failure, not a field the browser can check, so
      // it lands on the field rather than in a whole-form banner.
      form.setError('pin', {
        message: error instanceof Error ? error.message : 'That did not work. Try again.',
      })
    }
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>

        <form
          id="pin-form"
          onSubmit={(event) => void submit(event)}
          className="space-y-4"
          noValidate
        >
          <FormError message={null} />

          <Field
            id="pin"
            label={mode === 'change' ? 'New PIN' : 'PIN'}
            hint={
              needsConfirmation
                ? `At least ${MIN_PIN_LENGTH} characters. Longer is much harder to guess.`
                : undefined
            }
            error={form.formState.errors.pin?.message}
          >
            {(props) => (
              <Input
                type="password"
                inputMode="numeric"
                autoComplete={needsConfirmation ? 'new-password' : 'current-password'}
                autoFocus
                {...props}
                {...form.register('pin')}
              />
            )}
          </Field>

          {needsConfirmation ? (
            <Field
              id="confirm"
              label="Type it again"
              error={form.formState.errors.confirm?.message}
            >
              {(props) => (
                <Input
                  type="password"
                  autoComplete="new-password"
                  {...props}
                  {...form.register('confirm')}
                />
              )}
            </Field>
          ) : null}

          {mode === 'set-up' ? (
            <Alert variant="destructive">
              <AlertTitle>Write this PIN down somewhere safe</AlertTitle>
              <AlertDescription>
                Nobody can recover it, not even the app. If you lose it, every client name is gone
                for good. Every fee, session and euro survives.
              </AlertDescription>
            </Alert>
          ) : null}
        </form>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="pin-form" pending={form.formState.isSubmitting}>
            {copy.action}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
