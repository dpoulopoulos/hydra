import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Users, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import {
  householdsAcceptReceivedHouseholdInvite,
  householdsListReceivedHouseholdInvites,
  type HouseholdInviteReceived,
} from '@/api'
import { SubmitButton } from '@/components/submit-button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { errorMessage } from '@/lib/api'
import { formatDateTime } from '@/lib/month'

/**
 * Offers the invitations waiting for the signed-in account.
 *
 * Signing up through an invitation link does not take the invitation: it
 * becomes the account's to accept once the address is verified. Without this,
 * the only way to accept it was to dig the link back out of the email.
 */
export function InviteBanner() {
  const [dismissed, setDismissed] = useState<string[]>([])

  const { data } = useQuery({
    queryKey: ['receivedInvites'],
    queryFn: async () => {
      const { data, error } = await householdsListReceivedHouseholdInvites()
      if (error) throw error
      return data
    },
  })

  const invites = (data?.data ?? []).filter((invite) => !dismissed.includes(invite.id))

  if (invites.length === 0) return null

  return (
    <div className="space-y-3">
      {invites.map((invite) => (
        <InviteAlert
          key={invite.id}
          invite={invite}
          onDismiss={() => setDismissed((ids) => [...ids, invite.id])}
        />
      ))}
    </div>
  )
}

function InviteAlert({
  invite,
  onDismiss,
}: {
  invite: HouseholdInviteReceived
  onDismiss: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const accept = useMutation({
    mutationFn: async () => {
      const { data, error } = await householdsAcceptReceivedHouseholdInvite({
        path: { invite_id: invite.id },
      })
      if (error) throw error
      return data
    },
    onSuccess: async (household) => {
      // The household changed, so anything cached about the old one is stale.
      // Reset rather than clear: the shell and the page stay mounted, and a
      // cleared cache leaves them showing the old household until a reload.
      // The signed-in user is the same person, so it is kept, and the app is
      // not sent back to its full-page spinner.
      await queryClient.resetQueries({ predicate: (query) => query.queryKey[0] !== 'currentUser' })
      toast.success(`You joined ${household?.name ?? invite.household_name}`)
      navigate('/', { replace: true })
    },
    onError: (error) => toast.error(errorMessage(error, 'Could not join the household.')),
  })

  return (
    <Alert>
      <Users className="size-4" />
      <AlertTitle>Join {invite.household_name}</AlertTitle>
      <AlertDescription>
        <p>
          {invite.invited_by} invited you as {invite.role === 'owner' ? 'an owner' : 'a member'}.
          You will share the same accounts, budgets and transactions. The invitation expires on{' '}
          {formatDateTime(invite.expires_at)}.
        </p>
        <div className="mt-2 flex gap-2">
          <SubmitButton pending={accept.isPending} type="button" onClick={() => accept.mutate()}>
            Join household
          </SubmitButton>
          <Button type="button" variant="ghost" onClick={onDismiss}>
            <X className="size-4" />
            Not now
          </Button>
        </div>
      </AlertDescription>
    </Alert>
  )
}
