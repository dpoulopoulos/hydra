import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, KeyRound, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import type { ApiTokenCreated, ApiTokenPublic } from '@/api'
import {
  ApiTokenScope,
  apiTokensCreateApiToken,
  apiTokensListApiTokens,
  apiTokensRevokeApiToken,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { Field, FormError } from '@/components/form-field'
import { PageHeader } from '@/components/layout/page-header'
import { SettingsNav } from '@/components/layout/settings-nav'
import { SubmitButton } from '@/components/submit-button'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { errorMessage } from '@/lib/api'

const MIN_LIFETIME_DAYS = 1
const MAX_LIFETIME_DAYS = 730

const createSchema = z.object({
  name: z.string().trim().min(1, 'Give the token a name.').max(255),
  scope: z.enum(ApiTokenScope),
  expires_in_days: z.coerce
    .number()
    .int()
    .min(MIN_LIFETIME_DAYS)
    .max(MAX_LIFETIME_DAYS, `At most ${MAX_LIFETIME_DAYS} days.`),
})

// The number field hands back a string, so what goes in and what comes out of
// the schema are different types.
type Values = z.input<typeof createSchema>
type Parsed = z.output<typeof createSchema>

// React Compiler will not memoize a component that calls React Hook Form's
// `watch()`, and skips it whole. That skip is what this form relies on:
// `form.reset()` empties the field map after a token is minted and counts on
// the next render calling `register()` again, which a memoized render never
// repeats, leaving every field unregistered and the form with nothing to
// send. Nothing goes stale in return, since `watch()` re-renders this
// component and the access picker is handed the value from that render.
/* eslint-disable react-hooks/incompatible-library -- skipping this one is the point; see above */
export function Component() {
  const queryClient = useQueryClient()
  const [revoking, setRevoking] = useState<ApiTokenPublic | null>(null)
  // Held only until the dialog is dismissed. Nothing can reproduce the
  // secret, and nothing here writes it anywhere that outlives the page.
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)

  const tokens = useQuery({
    queryKey: ['apiTokens'],
    queryFn: async () => {
      const { data, error } = await apiTokensListApiTokens()
      if (error) throw error
      return data
    },
  })

  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(createSchema),
    // Read only by default. A token that can spend money should be a thing
    // somebody chose, not a thing they got.
    defaultValues: { name: '', scope: ApiTokenScope.READ, expires_in_days: 90 },
  })

  const create = useMutation({
    mutationFn: async (values: Parsed) => {
      const { data, error } = await apiTokensCreateApiToken({ body: values })
      if (error) throw error
      return data
    },
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ['apiTokens'] })
      form.reset({ name: '', scope: ApiTokenScope.READ, expires_in_days: 90 })
      setCreated(created)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const revoke = useMutation({
    mutationFn: async (token: ApiTokenPublic) => {
      const { error } = await apiTokensRevokeApiToken({ path: { token_id: token.id } })
      if (error) throw error
      return token
    },
    onSuccess: (token) => {
      void queryClient.invalidateQueries({ queryKey: ['apiTokens'] })
      setRevoking(null)
      toast.success(`${token.name} revoked`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Tokens that let a program use hydra on your behalf."
      />
      <SettingsNav />

      <Card>
        <CardHeader>
          <CardTitle>New token</CardTitle>
          <CardDescription>
            A token reads everything you can. Give it write access only if you want a program
            recording transactions for you. No token can sign in, change your password or your
            address, or manage who is in the household.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form
            onSubmit={form.handleSubmit((values) => create.mutate(values))}
            className="flex flex-wrap items-start gap-3"
          >
            <Field
              id="token-name"
              label="What is it for"
              error={form.formState.errors.name?.message}
              className="min-w-56 flex-1"
            >
              {(props) => <Input {...props} {...form.register('name')} placeholder="Claude" />}
            </Field>
            <Field
              id="token-scope"
              label="Access"
              error={form.formState.errors.scope?.message}
              className="w-44"
            >
              {(props) => (
                <Select
                  value={form.watch('scope')}
                  onValueChange={(value) => form.setValue('scope', value as ApiTokenScope)}
                >
                  <SelectTrigger id={props.id} className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ApiTokenScope.READ}>Read only</SelectItem>
                    <SelectItem value={ApiTokenScope.READ_WRITE}>Read and write</SelectItem>
                  </SelectContent>
                </Select>
              )}
            </Field>
            <Field
              id="token-expiry"
              label="Expires in (days)"
              error={form.formState.errors.expires_in_days?.message}
              className="w-32"
            >
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  min={MIN_LIFETIME_DAYS}
                  max={MAX_LIFETIME_DAYS}
                  {...form.register('expires_in_days')}
                />
              )}
            </Field>
            <SubmitButton pending={create.isPending} className="mt-6">
              Create token
            </SubmitButton>
          </form>
          <FormError message={create.isError ? errorMessage(create.error) : null} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Your tokens</CardTitle>
          <CardDescription>
            Revoking one stops it working straight away. Anything using it will need a new one.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {tokens.isPending ? (
            <LoadingRows rows={2} />
          ) : tokens.isError ? (
            <ErrorState error={tokens.error} />
          ) : tokens.data.count === 0 ? (
            <EmptyState
              icon={KeyRound}
              title="No tokens yet"
              description="Create one above to let a program use hydra for you."
            />
          ) : (
            <ul className="divide-y">
              {tokens.data.data.map((token) => (
                <li key={token.id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 truncate font-medium">
                      {token.name}
                      {token.scope === 'read' ? <Badge variant="secondary">Read only</Badge> : null}
                    </p>
                    <p className="text-muted-foreground truncate text-sm">{describe(token)}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setRevoking(token)}
                    aria-label={`Revoke ${token.name}`}
                  >
                    <Trash2 className="size-4" />
                    Revoke
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <SecretDialog created={created} onDismiss={() => setCreated(null)} />

      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        // The name on its own reads as "revoke Claude", which sounds like a
        // person rather than a credential. The identifier is here because two
        // tokens may be called the same thing, and it is the one part of the
        // row that tells them apart. It is kept on one line with the name,
        // because a hex string broken across two is hard to read back.
        title="Revoke this token?"
        // Matched to the variant the base class uses, so tailwind-merge
        // replaces it rather than leaving two widths for the cascade to pick
        // between. The default is too narrow for a name and an identifier on
        // one line.
        className="data-[size=default]:sm:max-w-xl"
        description={
          revoking && (
            <>
              <span className="whitespace-nowrap">
                <span className="text-foreground font-medium">{revoking.name}</span>{' '}
                <span className="font-mono text-xs">{revoking.token_id}</span>
              </span>{' '}
              stops working right away, and cannot be brought back.
            </>
          )
        }
        confirmLabel="Revoke token"
        onConfirm={() => revoking && revoke.mutate(revoking)}
        pending={revoke.isPending}
      />
    </div>
  )
}

/**
 * The one time the secret is ever shown.
 *
 * Only a hash of it is stored, so this cannot be reopened later. The dialog
 * says so before the button that dismisses it, rather than after.
 */
function SecretDialog({
  created,
  onDismiss,
}: {
  created: ApiTokenCreated | null
  onDismiss: () => void
}) {
  const [copied, setCopied] = useState(false)
  const secret = created?.secret ?? null

  const copy = async () => {
    if (!secret) return
    try {
      await navigator.clipboard.writeText(secret)
    } catch {
      // A browser may refuse the clipboard outright, and this is the one
      // moment where losing the token costs you the token. Say so, rather
      // than leaving the icon unchanged and the failure unhandled.
      toast.error('Could not copy. Select the token and copy it yourself.')
      return
    }
    setCopied(true)
    toast.success('Token copied')
  }

  return (
    <Dialog
      open={created !== null}
      onOpenChange={(open) => {
        if (!open) {
          setCopied(false)
          onDismiss()
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Copy your token now</DialogTitle>
          <DialogDescription>
            This is the only time it is shown. We keep only a hash of it, so if you lose it you will
            have to create another.
            {created?.token.scope === 'read_write'
              ? ' This one can change your data, not only read it.'
              : ''}
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-start gap-2">
          {/* The token is one long unbroken string. Wrapping it rather than
              truncating keeps all of it selectable, and break-all stops it
              forcing the dialog wider than the screen. */}
          <code className="bg-muted min-w-0 flex-1 rounded-md px-3 py-2 font-mono text-sm break-all">
            {secret}
          </code>
          <Button
            variant="outline"
            size="icon"
            className="shrink-0"
            onClick={() => void copy()}
            aria-label="Copy token"
          >
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={onDismiss}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** The second line of a token: when it was last used, and when it runs out. */
function describe(token: ApiTokenPublic): string {
  const used = token.last_used_at ? `Last used ${formatDate(token.last_used_at)}` : 'Never used'
  const expires = token.expires_at ? `expires ${formatDate(token.expires_at)}` : 'no expiry'

  return `${used} · ${expires} · ${token.token_id}`
}

function formatDate(value: string): string {
  // The backend sends these without a zone; they are UTC.
  const withZone = value.endsWith('Z') || value.includes('+') ? value : `${value}Z`
  return new Date(withZone).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}
