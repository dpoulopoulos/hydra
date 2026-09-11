import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { MailCheck, MailWarning, Send } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useSearchParams } from 'react-router'
import { z } from 'zod'

import { type EmailDelivery, householdsPreviewHouseholdInvite, usersRegisterUser } from '@/api'
import { Field, FormError } from '@/components/form-field'
import { AuthLayout } from '@/components/layout/auth-layout'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Input } from '@/components/ui/input'
import { errorMessage } from '@/lib/api'

// The backend hashes with bcrypt, which takes at most 72 bytes, and requires
// at least 8 characters. Mirrored here so the rule is explained before the
// request rather than after it.
const schema = z.object({
  full_name: z.string().trim().max(255).optional(),
  email: z.email('Enter a valid email address.'),
  password: z
    .string()
    .min(8, 'Use at least 8 characters.')
    .refine((value) => new TextEncoder().encode(value).length <= 72, {
      message: 'That password is too long. Use at most 72 bytes.',
    }),
})

type Values = z.infer<typeof schema>

export function Component() {
  const [searchParams] = useSearchParams()
  const inviteToken = searchParams.get('token')
  const [formError, setFormError] = useState<string | null>(null)
  const [submittedEmail, setSubmittedEmail] = useState<string | null>(null)
  // What became of the message the signup sent. A provider that is down does not fail the
  // signup - the message waits in the outbox and goes out minutes later - so the screen has to
  // be able to say "still sending" rather than send somebody to an inbox with nothing in it.
  const [delivery, setDelivery] = useState<EmailDelivery>('sent')

  // When they arrived from an invitation link, say whose household they are
  // joining, so the page is not a bare sign-up form out of context.
  const { data: invite } = useQuery({
    queryKey: ['invitePreview', inviteToken],
    queryFn: async () => {
      const { data, error } = await householdsPreviewHouseholdInvite({
        path: { token: inviteToken! },
      })
      if (error) throw error
      return data
    },
    enabled: Boolean(inviteToken),
    retry: false,
  })

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: '', email: '', password: '' },
  })

  const signUp = useMutation({
    mutationFn: async (values: Values) => {
      const { data, error } = await usersRegisterUser({
        body: {
          email: values.email,
          password: values.password,
          full_name: values.full_name?.trim() || null,
          invite_token: inviteToken,
        },
      })
      if (error) throw error
      return data
    },
    // The reply says the same thing whether or not the address already has an
    // account, on purpose, so the address to confirm comes from the form rather
    // than from the response.
    onSuccess: (data, values) => {
      setDelivery(data?.delivery ?? 'sent')
      setSubmittedEmail(values.email)
    },
    onError: (error) => setFormError(errorMessage(error, 'Could not create the account.')),
  })

  if (submittedEmail) {
    // The invitation is not taken at sign-up: registering with an address does not prove the
    // mailbox is yours. Verifying it does, and that is when the invitation becomes theirs to
    // accept.
    //
    // None of these wordings says whether the address is registered: the reply is the same
    // either way, delivery included, and it is the email, not this page, that tells the holder
    // which one they got.
    const whatToDo = invite
      ? `Open the link in that email to activate your account. Then open the invitation again to join ${invite.household_name}. If that address already has an account, the message links you to sign in instead.`
      : 'Open the link in that email to activate your account. If that address already has an account, the message links you to sign in instead. You can close this page.'

    if (delivery === 'not_configured') {
      return (
        <AuthLayout title="Your account is waiting" description="Nothing to check for yet.">
          <Alert>
            <MailWarning className="size-4" />
            <AlertTitle>No message was sent</AlertTitle>
            <AlertDescription>
              Email is not set up on this server, so nothing was sent to {submittedEmail}. Ask
              whoever runs it to activate the account for you.
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

    const queued = delivery === 'queued'

    return (
      <AuthLayout
        title={queued ? 'Your message is on its way' : 'Check your email'}
        description="One step left."
      >
        <Alert>
          {queued ? <Send className="size-4" /> : <MailCheck className="size-4" />}
          <AlertTitle>
            {queued
              ? `Still sending the message to ${submittedEmail}`
              : `Message sent to ${submittedEmail}`}
          </AlertTitle>
          <AlertDescription>
            {queued ? `It should arrive shortly. ${whatToDo}` : whatToDo}
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
      title={invite ? `Join ${invite.household_name}` : 'Create your account'}
      description={
        invite
          ? `${invite.invited_by} invited you. You will share the same accounts, budgets and transactions.`
          : 'Track spending, set monthly budgets, and see where the money went.'
      }
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-foreground font-medium underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <form
        onSubmit={handleSubmit((values) => {
          setFormError(null)
          signUp.mutate(values)
        })}
        className="space-y-4"
        noValidate
      >
        <FormError message={formError} />

        <Field id="full_name" label="Name" error={errors.full_name?.message}>
          {(props) => (
            <Input
              {...props}
              {...register('full_name')}
              autoComplete="name"
              placeholder="Optional"
            />
          )}
        </Field>

        {/* The invited address is only ever shown masked, so it cannot be
            filled in for them: they type the address the invitation was sent
            to, and the backend accepts the sign-up only if it matches. */}
        <Field
          id="email"
          label="Email"
          hint={invite ? `Use the invited address, ${invite.masked_email}.` : undefined}
          error={errors.email?.message}
        >
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

        <Field
          id="password"
          label="Password"
          hint="At least 8 characters."
          error={errors.password?.message}
        >
          {(props) => (
            <Input
              {...props}
              {...register('password')}
              type="password"
              autoComplete="new-password"
            />
          )}
        </Field>

        <SubmitButton pending={signUp.isPending} className="w-full">
          Create account
        </SubmitButton>
      </form>
    </AuthLayout>
  )
}
