import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  LogOut,
  Mail,
  MoreHorizontal,
  ShieldCheck,
  ShieldOff,
  Trash2,
  UserMinus,
} from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
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
import { useHousehold } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { formatDate } from '@/lib/month'

const renameSchema = z.object({
  name: z.string().trim().min(1, 'Give the household a name.').max(255),
})
const inviteSchema = z.object({
  email: z.email('Enter a valid email address.'),
  role: z.enum(HouseholdRole),
})

export function Component() {
  const { user, signOut } = useAuth()
  const queryClient = useQueryClient()
  const household = useHousehold()
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
        query: { status: HouseholdInviteStatus.PENDING },
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
    values: household.data ? { name: household.data.name } : undefined,
    defaultValues: { name: '' },
  })

  const rename = useMutation({
    mutationFn: async (values: z.infer<typeof renameSchema>) => {
      const { error } = await householdsUpdateHouseholdMe({ body: { name: values.name } })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['household'] })
      toast.success('Household renamed')
    },
  })

  const inviteForm = useForm<z.infer<typeof inviteSchema>>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: '', role: HouseholdRole.MEMBER },
  })

  const invite = useMutation({
    mutationFn: async (values: z.infer<typeof inviteSchema>) => {
      const { error } = await householdsCreateHouseholdInvite({ body: values })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['household', 'invites'] })
      inviteForm.reset({ email: '', role: HouseholdRole.MEMBER })
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
                    value={inviteForm.watch('role')}
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

            {invites.data && invites.data.count > 0 ? (
              <ul className="divide-y border-t">
                {invites.data.data.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{item.email}</p>
                      <p className="text-muted-foreground text-sm">
                        {item.role === HouseholdRole.OWNER ? 'Owner' : 'Member'} · expires{' '}
                        {formatDate(item.expires_at)}
                      </p>
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
