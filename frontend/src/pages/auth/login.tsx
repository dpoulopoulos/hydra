import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useLocation, useNavigate } from 'react-router'
import { z } from 'zod'

import { Field, FormError } from '@/components/form-field'
import { AuthLayout } from '@/components/layout/auth-layout'
import { SubmitButton } from '@/components/submit-button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/use-auth'

const schema = z.object({
  email: z.email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
})

type Values = z.infer<typeof schema>

/**
 * Wherever they were headed before the gate sent them here.
 *
 * The whole address, not only the path: a bank sends its login back with the
 * code in the query string, and a session that ran out meanwhile must not
 * cost the connection.
 */
function returnPath(state: unknown): string {
  const from = (state as { from?: { pathname: string; search?: string; hash?: string } } | null)
    ?.from
  if (!from) return '/'
  return `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`
}

export function Component() {
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [formError, setFormError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { email: '', password: '' } })

  const onSubmit = async (values: Values) => {
    setFormError(null)
    try {
      await signIn(values.email, values.password)
      navigate(returnPath(location.state), { replace: true })
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Could not sign in. Try again.')
    }
  }

  return (
    <AuthLayout
      title="Sign in"
      description="Pick up where your household left off."
      footer={
        <>
          New here?{' '}
          <Link to="/signup" className="text-foreground font-medium underline underline-offset-4">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
        <FormError message={formError} />

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

        <Field id="password" label="Password" error={errors.password?.message}>
          {(props) => (
            <Input
              {...props}
              {...register('password')}
              type="password"
              autoComplete="current-password"
            />
          )}
        </Field>

        <SubmitButton pending={isSubmitting} className="w-full">
          Sign in
        </SubmitButton>

        <Link
          to="/forgot-password"
          className="text-muted-foreground hover:text-foreground block text-center text-sm underline underline-offset-4"
        >
          Forgot your password?
        </Link>
      </form>
    </AuthLayout>
  )
}
