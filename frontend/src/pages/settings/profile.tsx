import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { usersDeleteUserMe, usersUpdatePasswordMe, usersUpdateUserMe } from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { Field, FormError } from '@/components/form-field'
import { PageHeader } from '@/components/layout/page-header'
import { SettingsNav } from '@/components/layout/settings-nav'
import { SubmitButton } from '@/components/submit-button'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/use-auth'
import { errorMessage } from '@/lib/api'
import { PASSWORD_HINT, passwordSchema } from '@/lib/password'
import { useState } from 'react'

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
    values: user ? { full_name: user.full_name ?? '', email: user.email } : undefined,
    defaultValues: { full_name: '', email: '' },
  })

  const saveDetails = useMutation({
    mutationFn: async (values: z.infer<typeof detailsSchema>) => {
      const { error } = await usersUpdateUserMe({
        body: { full_name: values.full_name?.trim() || null, email: values.email },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['currentUser'] })
      toast.success('Profile saved')
    },
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
      passwordForm.reset({ current_password: '', new_password: '', confirm: '' })
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
          </CardDescription>
        </CardHeader>
        <CardContent>
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
