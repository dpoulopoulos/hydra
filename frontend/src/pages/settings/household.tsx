import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Clock,
  LogOut,
  Mail,
  MailWarning,
  MoreHorizontal,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserMinus,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  householdsCreateHouseholdInvite,
  householdsLeaveHousehold,
  householdsListHouseholdInvites,
  householdsListHouseholdMembers,
  householdsRemoveHouseholdMember,
  householdsRevokeHouseholdInvite,
  householdsUpdateHouseholdMe,
  householdsUpdateHouseholdMember,
  EmailOutboxStatus,
  HouseholdInviteStatus,
  HouseholdRole,
  type HouseholdInvitePublic,
  type HouseholdMemberPublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ErrorState, LoadingRows } from '@/components/data-state'
import { Field, FormError } from '@/components/form-field'
import { PageHeader } from '@/components/layout/page-header'
import { SettingsNav } from '@/components/layout/settings-nav'
import { SubmitButton } from '@/components/submit-button'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAuth } from '@/hooks/use-auth'
import { useCurrency, useHousehold } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { refill } from '@/lib/form'
import { describeLocale, HOUSEHOLD_LOCALES } from '@/lib/locales'
import { formatDateTime } from '@/lib/month'

/**
 * What became of the invitation email, when there is something to say about it.
 *
 * A delivered message says nothing: the common case should not be decorated.
 * Neither does a missing state, which is what an invitation made with mail
 * switched off, or one whose outbox row has been pruned, reports.
 */
function DeliveryBadge({ status }: { status?: EmailOutboxStatus | null }) {
  if (status === EmailOutboxStatus.FAILED) {
    return (
      <Badge variant="destructive" className="gap-1">
        <MailWarning className="size-3" />
        Not delivered
      </Badge>
    )
  }

  if (status === EmailOutboxStatus.PENDING) {
    return (
      <Badge variant="outline" className="gap-1">
        <Clock className="size-3" />
        Sending
      </Badge>
    )
  }

  return null
}

// What the picker calls "no locale of our own". Radix gives an option's value
// to the DOM, where an empty string means "nothing selected" rather than a
// choice, so the absence of a locale needs a name of its own.
const NO_LOCALE = 'browser'

const renameSchema = z.object({
  name: z.string().trim().min(1, 'Give the household a name.').max(255),
})
const inviteSchema = z.object({
  email: z.email('Enter a valid email address.'),
  role: z.enum(HouseholdRole),
})

// How many outstanding invitations the card asks for. A household invites a
// handful of people, so one page holds them all in practice; the point is that
// a household which has invited far more does not pull every row into this
// list. What did not fit is counted under the list rather than paged, since
// nobody is expected to get there.
const INVITE_PAGE_SIZE = 50

export function Component() {
  const { user, signOut } = useAuth()
  const queryClient = useQueryClient()
  const household = useHousehold()
  const currency = useCurrency()
  const [removing, setRemoving] = useState<HouseholdMemberPublic | null>(null)
  const [leaving, setLeaving] = useState(false)
  const [revoking, setRevoking] = useState<HouseholdInvitePublic | null>(null)

  const members = useQuery({
    queryKey: ['household', 'members'],
    queryFn: async () => {
      const { data, error } = await householdsListHouseholdMembers()
      if (error) throw error
      return data
    },
  })

  const invites = useQuery({
    queryKey: ['household', 'invites'],
    queryFn: async () => {
      const { data, error } = await householdsListHouseholdInvites({
        query: { status: HouseholdInviteStatus.PENDING, limit: INVITE_PAGE_SIZE },
      })
      if (error) throw error
      return data
    },
  })

  // Only an owner manages the household itself; everyone shares the money.
  const isOwner =
    members.data?.data.find((member) => member.user_id === user?.id)?.role === HouseholdRole.OWNER

  const renameForm = useForm<z.infer<typeof renameSchema>>({
    resolver: zodResolver(renameSchema),
    defaultValues: { name: '' },
  })

  // The household is cached for the session and fetched again on window focus,
  // so its name can arrive at any moment. Fill the field in from an effect
  // with `keepDirtyValues`, so an answer landing mid-rename leaves what is
  // being typed alone: handing the form to the query would quietly submit the
  // old name the field had stopped showing.
  const { reset: resetRenameForm } = renameForm
  const householdName = household.data?.name
  useEffect(() => {
    if (householdName !== undefined) {
      resetRenameForm({ name: householdName }, { keepFieldsRef: true, keepDirtyValues: true })
    }
  }, [householdName, resetRenameForm])

  const rename = useMutation({
    mutationFn: async (values: z.infer<typeof renameSchema>) => {
      const { error } = await householdsUpdateHouseholdMe({ body: { name: values.name } })
      if (error) throw error
    },
    onSuccess: (_data, values) => {
      // The name that was saved is the new baseline. Without this the field
      // stays marked as edited and would ignore every later answer about the
      // household, including a rename made from another device.
      renameForm.resetField('name', { defaultValue: values.name })
      void queryClient.invalidateQueries({ queryKey: ['household'] })
      toast.success('Household renamed')
    },
  })

  const setLocale = useMutation({
    mutationFn: async (locale: string | null) => {
      const { error } = await householdsUpdateHouseholdMe({ body: { locale } })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['household'] })
      toast.success('Number format saved')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const inviteForm = useForm<z.infer<typeof inviteSchema>>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: '', role: HouseholdRole.MEMBER },
  })

  // Watched through `useWatch()` rather than the form's own `watch()`, which
  // hands back a function React Compiler will not memoize and skips the whole
  // page over.
  const invitedRole = useWatch({ control: inviteForm.control, name: 'role' })

  const invite = useMutation({
    mutationFn: async (values: z.infer<typeof inviteSchema>) => {
      const { error } = await householdsCreateHouseholdInvite({ body: values })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['household', 'invites'] })
      refill(inviteForm, { email: '', role: HouseholdRole.MEMBER })
      toast.success('Invitation sent')
    },
  })

  const setRole = useMutation({
    mutationFn: async ({
      member,
      role,
    }: {
      member: HouseholdMemberPublic
      role: HouseholdRole
    }) => {
      const { error } = await householdsUpdateHouseholdMember({
        path: { user_id: member.user_id },
        body: { role },
      })
      if (error) throw error
      return { member, role }
    },
    onSuccess: ({ member, role }) => {
      void queryClient.invalidateQueries({ queryKey: ['household'] })
      toast.success(
        role === HouseholdRole.OWNER
          ? `${member.email} can now manage the household`
          : `${member.email} is now a member`,
      )
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const removeMember = useMutation({
    mutationFn: async (member: HouseholdMemberPublic) => {
      const { error } = await householdsRemoveHouseholdMember({ path: { user_id: member.user_id } })
      if (error) throw error
      return member
    },
    onSuccess: (member) => {
      void queryClient.invalidateQueries({ queryKey: ['household'] })
      setRemoving(null)
      toast.success(`${member.email} removed`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const leave = useMutation({
    mutationFn: async () => {
      const { error } = await householdsLeaveHousehold()
      if (error) throw error
    },
    onSuccess: () => {
      // They now belong to a fresh, empty household, so nothing cached applies.
      signOut()
      toast.success('You left the household. Sign in again to start fresh.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const revoke = useMutation({
    mutationFn: async (item: HouseholdInvitePublic) => {
      const { error } = await householdsRevokeHouseholdInvite({ path: { invite_id: item.id } })
      if (error) throw error
      return item
    },
    onSuccess: (item) => {
      void queryClient.invalidateQueries({ queryKey: ['household', 'invites'] })
      setRevoking(null)
      toast.success(`Invitation to ${item.email} withdrawn`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <>
      <PageHeader title="Settings" description="Your household, your account." />
      <SettingsNav />

      <Card>
        <CardHeader>
          <CardTitle>Household</CardTitle>
          <CardDescription>
            Everyone here shares the same accounts, categories, budgets and transactions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={renameForm.handleSubmit((values) => rename.mutate(values))}
            className="flex flex-wrap items-end gap-3"
            noValidate
          >
            <Field
              id="household-name"
              label="Name"
              error={renameForm.formState.errors.name?.message}
              className="min-w-64 flex-1"
            >
              {(props) => <Input {...props} {...renameForm.register('name')} disabled={!isOwner} />}
            </Field>
            {isOwner ? (
              <SubmitButton pending={rename.isPending}>Save name</SubmitButton>
            ) : (
              <p className="text-muted-foreground pb-2 text-sm">Only an owner can rename it.</p>
            )}
          </form>
          <FormError message={rename.isError ? errorMessage(rename.error) : null} />

          <Field
            id="household-numbers"
            label="Numbers"
            hint="How amounts are written and read on every screen here, for everyone in the household."
            className="mt-4 max-w-sm"
          >
            {(props) => (
              <Select
                value={household.data?.locale ?? NO_LOCALE}
                onValueChange={(value) => setLocale.mutate(value === NO_LOCALE ? null : value)}
                disabled={!isOwner || setLocale.isPending}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {/* The first option is what every household had before it
                      could choose: each person's own browser decides, so two
                      people may be shown the same amount differently. */}
                  <SelectItem value={NO_LOCALE}>Each reader&apos;s browser</SelectItem>
                  {HOUSEHOLD_LOCALES.map((locale) => (
                    <SelectItem key={locale} value={locale}>
                      {describeLocale(locale, currency)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
          <CardDescription>
            {members.data
              ? `${members.data.count} ${members.data.count === 1 ? 'person' : 'people'} in this household.`
              : 'Who shares this household.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {members.isPending ? (
            <LoadingRows rows={2} />
          ) : members.isError ? (
            <ErrorState error={members.error} />
          ) : (
            <ul className="divide-y">
              {(members.data?.data ?? []).map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 truncate font-medium">
                      {member.full_name ?? member.email}
                      {member.role === HouseholdRole.OWNER ? (
                        <Badge variant="secondary" className="gap-1">
                          <ShieldCheck className="size-3" />
                          Owner
                        </Badge>
                      ) : null}
                      {member.user_id === user?.id ? <Badge variant="outline">You</Badge> : null}
                    </p>
                    {/* Only worth a second line when the name above is not
                        already the address. */}
                    {member.full_name ? (
                      <p className="text-muted-foreground truncate text-sm">{member.email}</p>
                    ) : null}
                  </div>

                  {member.user_id === user?.id ? (
                    <Button variant="ghost" size="sm" onClick={() => setLeaving(true)}>
                      <LogOut className="size-4" />
                      Leave
                    </Button>
                  ) : isOwner ? (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="icon" aria-label={`Manage ${member.email}`}>
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          onClick={() =>
                            setRole.mutate({
                              member,
                              role:
                                member.role === HouseholdRole.OWNER
                                  ? HouseholdRole.MEMBER
                                  : HouseholdRole.OWNER,
                            })
                          }
                        >
                          {member.role === HouseholdRole.OWNER ? (
                            <>
                              <ShieldOff className="size-4" />
                              Make them a member
                            </>
                          ) : (
                            <>
                              <ShieldCheck className="size-4" />
                              Make them an owner
                            </>
                          )}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem variant="destructive" onClick={() => setRemoving(member)}>
                          <UserMinus className="size-4" />
                          Remove from household
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {isOwner ? (
        <Card>
          <CardHeader>
            <CardTitle>Invitations</CardTitle>
            <CardDescription>
              An invitation is good for seven days and only works from the address it was sent to.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <form
              onSubmit={inviteForm.handleSubmit((values) => invite.mutate(values))}
              className="flex flex-wrap items-end gap-3"
              noValidate
            >
              <Field
                id="invite-email"
                label="Email"
                error={inviteForm.formState.errors.email?.message}
                className="min-w-56 flex-1"
              >
                {(props) => (
                  <Input
                    {...props}
                    {...inviteForm.register('email')}
                    type="email"
                    placeholder="partner@example.com"
                  />
                )}
              </Field>
              <Field
                id="invite-role"
                label="Role"
                error={inviteForm.formState.errors.role?.message}
              >
                {(props) => (
                  <Select
                    value={invitedRole}
                    onValueChange={(value) => inviteForm.setValue('role', value as HouseholdRole)}
                  >
                    <SelectTrigger id={props.id} className="w-36">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={HouseholdRole.MEMBER}>Member</SelectItem>
                      <SelectItem value={HouseholdRole.OWNER}>Owner</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              </Field>
              <SubmitButton pending={invite.isPending}>
                <Mail className="size-4" />
                Send invitation
              </SubmitButton>
            </form>
            <FormError message={invite.isError ? errorMessage(invite.error) : null} />

            {invites.isPending ? (
              <LoadingRows rows={2} />
            ) : invites.isError ? (
              // Told "none outstanding", an owner re-invites someone and gets
              // a 409 back saying that address is already invited.
              <ErrorState error={invites.error} title="Invitations did not load" />
            ) : invites.data.data.length > 0 ? (
              <ul className="divide-y border-t">
                {invites.data.data.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="flex items-center gap-2 font-medium">
                        <span className="truncate">{item.email}</span>
                        <DeliveryBadge status={item.delivery_status} />
                      </p>
                      <p className="text-muted-foreground text-sm">
                        {item.role === HouseholdRole.OWNER ? 'Owner' : 'Member'} · expires{' '}
                        {formatDateTime(item.expires_at)}
                      </p>
                      {/* The invitation is valid either way, so the way out is
                          to send it again rather than to wait. */}
                      {item.delivery_status === EmailOutboxStatus.FAILED ? (
                        <p className="text-destructive text-sm">
                          We could not deliver this invitation. Withdraw it and invite them again,
                          or pass the invitation on yourself.
                        </p>
                      ) : null}
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => setRevoking(item)}>
                      <Trash2 className="size-4" />
                      Withdraw
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-muted-foreground border-t pt-3 text-sm">
                No invitations outstanding.
              </p>
            )}
            {!invites.isPending &&
            !invites.isError &&
            invites.data.count > invites.data.data.length ? (
              <p className="text-muted-foreground pt-3 text-sm">
                Showing {invites.data.data.length} of {invites.data.count} outstanding invitations.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove ${removing?.email}?`}
        description="They keep their account and get a fresh, empty household. The transactions they recorded here stay."
        confirmLabel="Remove them"
        pending={removeMember.isPending}
        onConfirm={() => removing && removeMember.mutate(removing)}
      />

      <ConfirmDialog
        open={leaving}
        onOpenChange={setLeaving}
        title="Leave this household?"
        description="You keep your account and get a fresh, empty household. Everything recorded here stays with the others. You will be signed out."
        confirmLabel="Leave household"
        pending={leave.isPending}
        onConfirm={() => leave.mutate()}
      />

      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={`Withdraw the invitation to ${revoking?.email}?`}
        description="The link stops working. Anyone following it is told it was withdrawn."
        confirmLabel="Withdraw it"
        pending={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
      />
    </>
  )
}
