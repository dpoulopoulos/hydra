import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, Loader2, MailWarning, Send } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router'
import { z } from 'zod'

import {
  type EmailDelivery,
  emailVerificationResendVerificationEmail,
  emailVerificationVerifyEmail,
} from '@/api'
import { Field, FormError } from '@/components/form-field'
import { AuthLayout } from '@/components/layout/auth-layout'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { errorMessage } from '@/lib/api'

const schema = z.object({ email: z.email('Enter a valid email address.') })

type Values = z.infer<typeof schema>

export function Component() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const attempted = useRef(false)

  const verify = useMutation({
    mutationFn: async (value: string) => {
      const { data, error } = await emailVerificationVerifyEmail({ body: { token: value } })
      if (error) throw error
      return data?.message ?? ''
    },
  })

  const resend = useMutation({
    mutationFn: async (values: Values) => {
      const { data, error } = await emailVerificationResendVerificationEmail({
        body: { email: values.email },
      })
      if (error) throw error
      // What the server is doing with outbound mail. It says the same thing for an address that
      // has an account and one that does not, so wording the screen from it gives nothing away.
      return (data?.delivery ?? 'sent') as EmailDelivery
    },
  })

  // Verifying is the whole point of following the link, so it happens on
  // arrival rather than behind a button. The ref keeps it to one attempt.
  useEffect(() => {
    if (token && !attempted.current) {
      attempted.current = true
      verify.mutate(token)
    }
  }, [token, verify])

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: '' } })

  if (token && verify.isPending) {
    return (
      <AuthLayout title="Verifying your email" description="This takes a moment.">
        <div className="flex justify-center py-4">
          <Loader2 className="text-muted-foreground size-5 animate-spin" />
        </div>
      </AuthLayout>
    )
  }

  if (verify.isSuccess) {
    return (
      <AuthLayout title="Email verified" description="That address is yours.">
        <Alert>
          <CheckCircle2 className="size-4" />
          <AlertTitle>You are all set</AlertTitle>
          {/* The same link either activates an account or moves one to a new
              address, and only the server knows which this was. */}
          <AlertDescription>{verify.data}</AlertDescription>
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

  if (resend.isSuccess) {
    if (resend.data === 'not_configured') {
      return (
        <AuthLayout title="Nothing to check for" description="No mail is going out.">
          <Alert>
            <MailWarning className="size-4" />
            <AlertTitle>No message was sent</AlertTitle>
            <AlertDescription>
              Email is not set up on this server, so no link could be sent. Ask whoever runs it to
              activate the account for you.
            </AlertDescription>
          </Alert>
        </AuthLayout>
      )
    }

    // A link the server has written down but not yet handed over is not a link in an inbox. Say
    // so, rather than send somebody to look for something that is minutes away.
    if (resend.data === 'queued') {
      return (
        <AuthLayout title="Check your email" description="A fresh link is on its way.">
          <Alert>
            <Send className="size-4" />
            <AlertTitle>Still sending</AlertTitle>
            <AlertDescription>
              It should arrive shortly. Open the link in that email to activate your account.
            </AlertDescription>
          </Alert>
        </AuthLayout>
      )
    }

    return (
      <AuthLayout title="Check your email" description="A fresh link is on its way.">
        <Alert>
          <CheckCircle2 className="size-4" />
          <AlertTitle>Verification sent</AlertTitle>
          <AlertDescription>Open the link in that email to activate your account.</AlertDescription>
        </Alert>
      </AuthLayout>
    )
  }

  return (
    <AuthLayout
      title={token ? 'That link will not work' : 'Verify your email'}
      description={
        token ? 'It may have expired or already been used.' : 'Enter your address for a fresh link.'
      }
      footer={
        <Link to="/login" className="text-foreground font-medium underline underline-offset-4">
          Back to sign in
        </Link>
      }
    >
      <form
        onSubmit={handleSubmit((values) => resend.mutate(values))}
        className="space-y-4"
        noValidate
      >
        <FormError
          message={
            verify.isError
              ? errorMessage(verify.error)
              : resend.isError
                ? errorMessage(resend.error)
                : null
          }
        />

        <Field id="email" label="Email" error={errors.email?.message}>
          {(props) => (
            <Input
              {...props}
              {...register('email')}
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
            />
          )}
        </Field>

        <SubmitButton pending={resend.isPending} className="w-full">
          Send a new link
        </SubmitButton>
      </form>
    </AuthLayout>
  )
}
