import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { bankCompleteBankConnection } from '@/api'
import { ErrorState } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'

/**
 * Where the bank sends the browser back after its login.
 *
 * The bank puts a one-time code and the state hydra gave it in the query
 * string, or an error if the login was cancelled or refused. The code is
 * traded for the connection on arrival, and the reader is sent on to link
 * the accounts it reached.
 */
export function Component() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const code = searchParams.get('code')
  const state = searchParams.get('state')
  const refused = searchParams.get('error')
  const attempted = useRef(false)

  const complete = useMutation({
    mutationFn: async (body: { code: string; state: string }) => {
      const { data, error } = await bankCompleteBankConnection({ body })
      if (error || !data) throw error ?? new Error('The bank could not be connected.')
      return data
    },
    onSuccess: (connection) => {
      void queryClient.invalidateQueries({ queryKey: ['bank'] })
      toast.success(`${connection.aspsp_name} connected. Link its accounts to start syncing.`)
      // Replaced, so going back does not land here and spend the code twice.
      void navigate('/settings/bank', { replace: true })
    },
  })

  // The code is good for one go, so the ref keeps it to one attempt, even when
  // the effect runs twice in development.
  useEffect(() => {
    if (code && state && !refused && !attempted.current) {
      attempted.current = true
      complete.mutate({ code, state })
    }
  }, [code, state, refused, complete])

  const failure = refused
    ? (searchParams.get('error_description') ?? `The bank said: ${refused}.`)
    : !code || !state
      ? 'This address is missing what the bank sends back. Start again from the settings.'
      : complete.isError
        ? complete.error
        : null

  return (
    <div className="space-y-6">
      <PageHeader title="Connecting your bank" />
      {failure ? (
        <div className="max-w-xl space-y-4">
          <ErrorState error={failure} title="The bank was not connected" />
          <Button asChild variant="outline">
            <Link to="/settings/bank" replace>
              Back to banks
            </Link>
          </Button>
        </div>
      ) : (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Loader2 className="size-4 animate-spin" />
          Finishing the connection…
        </div>
      )}
    </div>
  )
}
