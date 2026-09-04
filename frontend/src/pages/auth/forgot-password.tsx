import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { MailCheck } from 'lucide-react'
import { useForm } from 'react-hook-form'
import { Link } from 'react-router'
import { z } from 'zod'

import { passwordResetRequestPasswordReset } from '@/api'
import { Field, FormError } from '@/components/form-field'
import { AuthLayout } from '@/components/layout/auth-layout'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { errorMessage } from '@/lib/api'

const schema = z.object({ email: z.email('Enter a valid email address.') })

type Values = z.infer<typeof schema>

export function Component() {
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: '' } })

  const request = useMutation({
    mutationFn: async (values: Values) => {
      const { error } = await passwordResetRequestPasswordReset({ body: { email: values.email } })
      if (error) throw error
    },
  })

  if (request.isSuccess) {
    return (
      <AuthLayout title="Check your email" description="If that address has an account.">
        <Alert>
          <MailCheck className="size-4" />
          <AlertTitle>Reset link sent to {getValues('email')}</AlertTitle>
          <AlertDescription>
            The link is good for 24 hours. Nothing arrives if the address has no account.
          </AlertDescription>
        </Alert>
        <Link
          to="/login"
          className="text-muted-foreground hover:text-foreground mt-4 block text-center text-sm underline underline-offset-4"
        >
          Back to sign in
        </Link>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title="Reset your password"
      description="We will email you a link to set a new one."
      footer={
        <Link to="/login" className="text-foreground font-medium underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <form
        onSubmit={handleSubmit((values) => request.mutate(values))}
        className="space-y-4"
        noValidate
      >
        <FormError message={request.isError ? errorMessage(request.error) : null} />

        <Field id="email" label="Email" error={errors.email?.message}>
          {(props) => (
            <Input
              {...props}
              {...register('email')}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              autoFocus
            />
          )}
        </Field>

        <SubmitButton pending={request.isPending} className="w-full">
          Send reset link
        </SubmitButton>
      </form>
    </AuthLayout>
  )
}
