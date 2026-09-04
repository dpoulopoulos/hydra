import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Users } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { householdsAcceptHouseholdInvite, householdsPreviewHouseholdInvite } from '@/api'
import { FormError } from '@/components/form-field'
import { AuthLayout } from '@/components/layout/auth-layout'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/hooks/use-auth'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/month'

export function Component() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const { isAuthenticated, isLoading } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const preview = useQuery({
    queryKey: ['invitePreview', token],
    queryFn: async () => {
      const { data, error } = await householdsPreviewHouseholdInvite({ path: { token } })
      if (error) throw error
      return data
    },
    enabled: token !== '',
    retry: false,
  })

  const accept = useMutation({
    mutationFn: async () => {
      const { data, error } = await householdsAcceptHouseholdInvite({ body: { token } })
      if (error) throw error
      return data
    },
    onSuccess: (household) => {
      // The household changed, so anything cached about the old one is stale.
      queryClient.clear()
      toast.success(`You joined ${household?.name ?? 'the household'}`)
      navigate('/', { replace: true })
    },
  })

  if (isLoading || (token !== '' && preview.isPending)) {
    return (
      <AuthLayout title="Checking the invitation" description="This takes a moment.">
        <div className="flex justify-center py-4">
          <Loader2 className="text-muted-foreground size-5 animate-spin" />
        </div>
      </AuthLayout>
    )
  }

  if (token === '' || preview.isError) {
    return (
      <AuthLayout
        title="That invitation will not work"
        description="It may have expired or been used."
      >
        <p className="text-muted-foreground text-sm">
          {token === '' ? 'The link is missing its token.' : errorMessage(preview.error)}
        </p>
        <p className="text-muted-foreground mt-4 text-sm">
          Ask whoever invited you to send a new one.
        </p>
      </AuthLayout>
    )
  }

  const invite = preview.data!

  return (
    <AuthLayout
      title={`Join ${invite.household_name}`}
      description={`${invite.invited_by} invited you as ${invite.role === 'owner' ? 'an owner' : 'a member'}.`}
    >
      <Alert className="mb-4">
        <Users className="size-4" />
        <AlertTitle>Everything is shared</AlertTitle>
        <AlertDescription>
          You will both see and manage the same accounts, budgets and transactions. The invitation
          expires on {formatDate(invite.expires_at)}.
        </AlertDescription>
      </Alert>

      <FormError message={accept.isError ? errorMessage(accept.error) : null} />

      {isAuthenticated ? (
        <div className="mt-2 space-y-3">
          <p className="text-muted-foreground text-sm">
            The invitation is for {invite.masked_email}. Only that account can accept it.
          </p>
          <SubmitButton
            pending={accept.isPending}
            className="w-full"
            onClick={() => accept.mutate()}
            type="button"
          >
            Join household
          </SubmitButton>
        </div>
      ) : (
        <div className="mt-2 space-y-3">
          <p className="text-muted-foreground text-sm">
            The invitation is for {invite.masked_email}. Sign in with that address, or create an
            account with it, to accept it.
          </p>
          <Button asChild className="w-full">
            <Link to={`/signup?token=${encodeURIComponent(token)}`}>Create an account</Link>
          </Button>
          <Button asChild variant="outline" className="w-full">
            <Link to="/login">Sign in</Link>
          </Button>
        </div>
      )}
    </AuthLayout>
  )
}
