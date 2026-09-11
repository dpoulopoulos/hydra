import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Mail, TriangleAlert } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  emailVerificationCancelPendingEmailChangeMe,
  emailVerificationGetPendingEmailChangeMe,
  emailVerificationResendPendingEmailChangeMe,
  emailVerificationSendVerificationEmailMe,
  usersDeleteUserMe,
  usersUpdatePasswordMe,
  usersUpdateUserMe,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Field, FormError } from '@/components/form-field'
import { PageHeader } from '@/components/layout/page-header'
import { SettingsNav } from '@/components/layout/settings-nav'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/use-auth'
import { errorMessage, errorStatus } from '@/lib/api'
import { refill } from '@/lib/form'
import { formatDateTime } from '@/lib/month'
import { PASSWORD_HINT, passwordSchema } from '@/lib/password'
import { useEffect, useState } from 'react'

const detailsSchema = z.object({
  full_name: z.string().trim().max(255).optional(),
  email: z.email('Enter a valid email address.'),
})

const passwordFormSchema = z
  .object({
    current_password: z.string().min(1, 'Enter your current password.'),
    new_password: passwordSchema,
    confirm: z.string(),
  })
  .refine((values) => values.new_password === values.confirm, {
    message: 'Both passwords must match.',
    path: ['confirm'],
  })

export function Component() {
  const { user, signOut } = useAuth()
  const queryClient = useQueryClient()
  const [deleting, setDeleting] = useState(false)

  const detailsForm = useForm<z.infer<typeof detailsSchema>>({
    resolver: zodResolver(detailsSchema),
    defaultValues: { full_name: '', email: '' },
  })

  // The user is cached, so it arrives after the first render and can be
  // fetched again at any point, window focus included. Mirror it into the form
  // as it changes, field by field: `keepDirtyValues` leaves whatever is being
  // edited alone, where handing the whole form to the query would discard it
  // mid-sentence.
  const { reset: resetDetails } = detailsForm
  useEffect(() => {
    if (!user) return
    resetDetails({ full_name: user.full_name ?? '', email: user.email }, { keepDirtyValues: true })
  }, [user, resetDetails])

  // The account does not move to a new address until the link sent there is
  // opened, and the reply that said so is gone by the next reload. Asking the
  // API is the only way the screen can say a change is still outstanding, and
  // which address it went to.
  const pendingChange = useQuery({
    queryKey: ['pendingEmailChange'],
    queryFn: async () => {
      const { data, error } = await emailVerificationGetPendingEmailChangeMe()
      if (error) throw error
      return data ?? null
    },
  })

  // A change asked for by mistake was otherwise only shaken off by asking for
  // another one or by waiting the link out, which leaves it live in a mailbox
  // the account holder may not read.
  const cancelChange = useMutation({
    mutationFn: async () => {
      const { error } = await emailVerificationCancelPendingEmailChangeMe()
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['pendingEmailChange'] })
      toast.success('Email change cancelled')
    },
    onError: (error) => {
      // A 404 means the change went while the notice was on screen: the link
      // was opened, it lapsed, or asking for a confirmation email expired it.
      // The outcome is the one that was asked for, so say so in the screen's
      // own words rather than the backend's, and clear the notice that is now
      // describing a change nobody is waiting on.
      if (errorStatus(error) === 404) {
        void queryClient.invalidateQueries({ queryKey: ['pendingEmailChange'] })
        toast.success('That change is no longer outstanding.')
        return
      }

      toast.error(errorMessage(error))
    },
  })

  // A link that went to a mistyped address, or to a mailbox that swallowed it,
  // left retyping the same address into the form below as the only way to prod
  // it. Asking again here sends to the address already asked for, so the change
  // cannot be re-aimed somewhere new without going through the form.
  const resendChange = useMutation({
    mutationFn: async () => {
      const { error } = await emailVerificationResendPendingEmailChangeMe()
      if (error) throw error
    },
    onSuccess: () => {
      // A fresh link comes with a fresh deadline, so the one on screen is now
      // describing a link that has been replaced.
      void queryClient.invalidateQueries({ queryKey: ['pendingEmailChange'] })
      toast.success('Link sent again. Check the new address.')
    },
    onError: (error) => {
      // A 404 means the change went while the notice was on screen, the same
      // way cancelling can find it gone.
      if (errorStatus(error) === 404) {
        void queryClient.invalidateQueries({ queryKey: ['pendingEmailChange'] })
        toast.success('That change is no longer outstanding.')
        return
      }

      toast.error(errorMessage(error))
    },
  })

  const saveDetails = useMutation({
    mutationFn: async (values: z.infer<typeof detailsSchema>) => {
      const { error } = await usersUpdateUserMe({
        body: { full_name: values.full_name?.trim() || null, email: values.email },
      })
      if (error) throw error
      return values.email
    },
    onSuccess: (requestedEmail, values) => {
      // What was saved is the new baseline. Without this the fields stay
      // marked as edited and would ignore every later answer about the user.
      detailsForm.resetField('full_name', { defaultValue: values.full_name })

      void queryClient.invalidateQueries({ queryKey: ['currentUser'] })
      void queryClient.invalidateQueries({ queryKey: ['pendingEmailChange'] })

      // A new address is not the account's until the link sent to it is
      // followed, so the form goes back to saying which address the account
      // actually holds rather than the one that was asked for.
      if (user && requestedEmail !== user.email) {
        detailsForm.resetField('email', { defaultValue: user.email })
        toast.success(`Open the link we sent to ${requestedEmail} to finish the change`)
        return
      }

      detailsForm.resetField('email', { defaultValue: values.email })
      toast.success('Profile saved')
    },
  })

  // Confirming the address is what proves the account holds it, and some
  // things ask for that proof: a household invitation is only redeemable by
  // the account that has confirmed the address it was sent to. An account an
  // administrator created was never sent a confirmation, and one that changed
  // its address here has only a confirmation of the address it used to hold,
  // so both need a way to ask for one.
  const confirmEmail = useMutation({
    mutationFn: async () => {
      // Issuing a confirmation expires whatever verification the account had
      // outstanding, so asking for one here quietly calls off a change of
      // address that was still waiting on its link. Note which address that
      // was before the row is gone, so the reply can say what it cost.
      const calledOff = pendingChange.data?.new_email ?? null
      const { error } = await emailVerificationSendVerificationEmailMe()
      if (error) throw error
      return calledOff
    },
    onSuccess: (calledOff) => {
      // The notice above is now describing a change the server has expired.
      void queryClient.invalidateQueries({ queryKey: ['pendingEmailChange'] })

      if (calledOff) {
        toast.success(`Confirmation email sent. The change to ${calledOff} was cancelled.`)
        return
      }

      toast.success('Confirmation email sent. Check your inbox.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const passwordForm = useForm<z.infer<typeof passwordFormSchema>>({
    resolver: zodResolver(passwordFormSchema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  })

  const changePassword = useMutation({
    mutationFn: async (values: z.infer<typeof passwordFormSchema>) => {
      const { error } = await usersUpdatePasswordMe({
        body: { current_password: values.current_password, new_password: values.new_password },
      })
      if (error) throw error
    },
    onSuccess: () => {
      refill(passwordForm, { current_password: '', new_password: '', confirm: '' })
      toast.success('Password changed')
    },
  })

  const deleteAccount = useMutation({
    mutationFn: async () => {
      const { error } = await usersDeleteUserMe()
      if (error) throw error
    },
    onSuccess: () => {
      signOut()
      toast.success('Your account is gone.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <>
      <PageHeader title="Settings" description="Your household, your account." />
      <SettingsNav />

      <Card>
        <CardHeader>
          <CardTitle>Your details</CardTitle>
          <CardDescription>
            Your name appears next to anything you record, so the household can tell who added what.
            A new email address becomes yours once you open the link we send to it.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {pendingChange.isError ? (
            // A lookup that failed is not the same answer as no change at all,
            // and staying quiet about it tells the account it is waiting on
            // nothing. Say the screen could not find out, and offer another go.
            <Alert variant="destructive" className="max-w-md">
              <TriangleAlert />
              <AlertTitle>Could not check for a pending email change</AlertTitle>
              <AlertDescription className="space-y-3">
                <p>
                  If you asked to change your address, the change may still be waiting on its link.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  type="button"
                  disabled={pendingChange.isFetching}
                  onClick={() => void pendingChange.refetch()}
                >
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}

          {pendingChange.data ? (
            <Alert className="max-w-md">
              <Mail />
              <AlertTitle>Waiting on {pendingChange.data.new_email}</AlertTitle>
              <AlertDescription className="space-y-3">
                <p>
                  Open the link we sent there by {formatDateTime(pendingChange.data.expires_at)} to
                  finish the change. Until you do, this account keeps the address below.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    disabled={resendChange.isPending}
                    onClick={() => resendChange.mutate()}
                  >
                    Send the link again
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    type="button"
                    disabled={cancelChange.isPending}
                    onClick={() => cancelChange.mutate()}
                  >
                    Cancel the change
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          ) : null}

          <form
            onSubmit={detailsForm.handleSubmit((values) => saveDetails.mutate(values))}
            className="max-w-md space-y-4"
            noValidate
          >
            <FormError message={saveDetails.isError ? errorMessage(saveDetails.error) : null} />

            <Field
              id="full_name"
              label="Name"
              error={detailsForm.formState.errors.full_name?.message}
            >
              {(props) => (
                <Input {...props} {...detailsForm.register('full_name')} placeholder="Optional" />
              )}
            </Field>

            <Field id="email" label="Email" error={detailsForm.formState.errors.email?.message}>
              {(props) => <Input {...props} {...detailsForm.register('email')} type="email" />}
            </Field>

            <SubmitButton pending={saveDetails.isPending}>Save details</SubmitButton>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Confirm your email</CardTitle>
          <CardDescription>
            Confirming {user?.email ?? 'your address'} proves it is yours. You need to have done it
            before you can accept a household invitation sent to it, and again after you change it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <SubmitButton
            pending={confirmEmail.isPending}
            onClick={() => confirmEmail.mutate()}
            type="button"
          >
            Send confirmation email
          </SubmitButton>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Password</CardTitle>
          <CardDescription>Changing it here does not sign you out anywhere.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={passwordForm.handleSubmit((values) => changePassword.mutate(values))}
            className="max-w-md space-y-4"
            noValidate
          >
            <FormError
              message={changePassword.isError ? errorMessage(changePassword.error) : null}
            />

            <Field
              id="current_password"
              label="Current password"
              error={passwordForm.formState.errors.current_password?.message}
            >
              {(props) => (
                <Input
                  {...props}
                  {...passwordForm.register('current_password')}
                  type="password"
                  autoComplete="current-password"
                />
              )}
            </Field>

            <Field
              id="new_password"
              label="New password"
              hint={PASSWORD_HINT}
              error={passwordForm.formState.errors.new_password?.message}
            >
              {(props) => (
                <Input
                  {...props}
                  {...passwordForm.register('new_password')}
                  type="password"
                  autoComplete="new-password"
                />
              )}
            </Field>

            <Field
              id="confirm"
              label="Confirm new password"
              error={passwordForm.formState.errors.confirm?.message}
            >
              {(props) => (
                <Input
                  {...props}
                  {...passwordForm.register('confirm')}
                  type="password"
                  autoComplete="new-password"
                />
              )}
            </Field>

            <SubmitButton pending={changePassword.isPending}>Change password</SubmitButton>
          </form>
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <CardTitle>Delete your account</CardTitle>
          <CardDescription>
            This removes your account for good. If others share your household, what you recorded
            stays with them.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" onClick={() => setDeleting(true)}>
            Delete my account
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Delete your account?"
        description="Your sign-in stops working straight away and this cannot be undone."
        confirmLabel="Delete my account"
        pending={deleteAccount.isPending}
        onConfirm={() => deleteAccount.mutate()}
      />
    </>
  )
}
