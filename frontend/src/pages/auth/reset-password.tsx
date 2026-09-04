import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { CheckCircle2 } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router'
import { z } from 'zod'

import { passwordResetConfirmPasswordReset, passwordResetVerifyPasswordResetToken } from '@/api'
import { Field, FormError } from '@/components/form-field'
import { AuthLayout } from '@/components/layout/auth-layout'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { errorMessage } from '@/lib/api'
import { PASSWORD_HINT, passwordSchema } from '@/lib/password'

const schema = z
  .object({
    new_password: passwordSchema,
    confirm: z.string(),
  })
  .refine((values) => values.new_password === values.confirm, {
    message: 'Both passwords must match.',
    path: ['confirm'],
  })

type Values = z.infer<typeof schema>

export function Component() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  // Check the link before asking for a new password, so an expired one is
  // caught up front rather than after the visitor has typed twice.
  const check = useQuery({
    queryKey: ['passwordResetToken', token],
    queryFn: async () => {
      const { data, error } = await passwordResetVerifyPasswordResetToken({ body: { token } })
      if (error) throw error
      return data
    },
    enabled: token !== '',
    retry: false,
  })

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { new_password: '', confirm: '' },
  })

  const confirm = useMutation({
    mutationFn: async (values: Values) => {
      const { error } = await passwordResetConfirmPasswordReset({
        body: { token, new_password: values.new_password },
      })
      if (error) throw error
    },
  })

  if (token === '' || check.isError) {
    return (
      <AuthLayout title="That link will not work" description="It may have expired or been used.">
        <p className="text-muted-foreground text-sm">
          {token === '' ? 'The link is missing its token.' : errorMessage(check.error)}
        </p>
        <Link
          to="/forgot-password"
          className="text-foreground mt-4 block text-center text-sm font-medium underline underline-offset-4"
        >
          Ask for a new link
        </Link>
      </AuthLayout>
    )
  }

  if (confirm.isSuccess) {
    return (
      <AuthLayout title="Password changed" description="You can sign in with it now.">
        <Alert>
          <CheckCircle2 className="size-4" />
          <AlertTitle>All set</AlertTitle>
          <AlertDescription>Your new password is ready to use.</AlertDescription>
        </Alert>
        <Link
          to="/login"
          className="text-foreground mt-4 block text-center text-sm font-medium underline underline-offset-4"
        >
          Sign in
        </Link>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Set a new password"
      description="Choose something you have not used here before."
    >
      <form
        onSubmit={handleSubmit((values) => confirm.mutate(values))}
        className="space-y-4"
        noValidate
      >
        <FormError message={confirm.isError ? errorMessage(confirm.error) : null} />

        <Field
          id="new_password"
          label="New password"
          hint={PASSWORD_HINT}
          error={errors.new_password?.message}
        >
          {(props) => (
            <Input
              {...props}
              {...register('new_password')}
              type="password"
              autoComplete="new-password"
              autoFocus
            />
          )}
        </Field>

        <Field id="confirm" label="Confirm password" error={errors.confirm?.message}>
          {(props) => (
            <Input
              {...props}
              {...register('confirm')}
              type="password"
              autoComplete="new-password"
            />
          )}
        </Field>

        <SubmitButton pending={confirm.isPending || check.isPending} className="w-full">
          Change password
        </SubmitButton>
      </form>
    </AuthLayout>
  )
}
