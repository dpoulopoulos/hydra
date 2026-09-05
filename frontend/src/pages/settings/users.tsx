import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, ShieldCheck, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  usersCreateUser,
  usersDeleteUser,
  usersGetUsers,
  usersUpdateUser,
  type UserPublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { ErrorState, LoadingRows } from '@/components/data-state'
import { Field, FormError } from '@/components/form-field'
import { PageHeader } from '@/components/layout/page-header'
import { Pagination } from '@/components/pagination'
import { SettingsNav } from '@/components/layout/settings-nav'
import { SubmitButton } from '@/components/submit-button'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuth } from '@/hooks/use-auth'
import { errorMessage } from '@/lib/api'
import { PASSWORD_HINT, passwordSchema } from '@/lib/password'
import { formatInstantAsDate } from '@/lib/month'

const PAGE_SIZE = 25

const schema = z.object({
  full_name: z.string().trim().max(255).optional(),
  email: z.email('Enter a valid email address.'),
  password: passwordSchema,
})

/**
 * Every account on this deployment.
 *
 * Superusers only, and deliberately separate from the household screens: this
 * is about who can sign in, not about anyone's money. The household boundary
 * holds even here, so no figures appear.
 */
export function Component() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [page, setPage] = useState(0)
  const [deleting, setDeleting] = useState<UserPublic | null>(null)

  const users = useQuery({
    queryKey: ['users', page],
    queryFn: async () => {
      const { data, error } = await usersGetUsers({
        query: { skip: page * PAGE_SIZE, limit: PAGE_SIZE },
      })
      if (error) throw error
      return data
    },
    enabled: Boolean(user?.is_superuser),
  })

  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: '', email: '', password: '' },
  })

  const create = useMutation({
    mutationFn: async (values: z.infer<typeof schema>) => {
      const { error } = await usersCreateUser({
        body: {
          email: values.email,
          password: values.password,
          full_name: values.full_name?.trim() || null,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      form.reset({ full_name: '', email: '', password: '' })
      setCreating(false)
      toast.success('Account created')
    },
  })

  const setActive = useMutation({
    mutationFn: async ({ target, active }: { target: UserPublic; active: boolean }) => {
      const { error } = await usersUpdateUser({
        path: { user_id: target.id },
        body: { is_active: active },
      })
      if (error) throw error
      return { target, active }
    },
    onSuccess: ({ target, active }) => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      toast.success(active ? `${target.email} activated` : `${target.email} deactivated`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const remove = useMutation({
    mutationFn: async (target: UserPublic) => {
      const { error } = await usersDeleteUser({ path: { user_id: target.id } })
      if (error) throw error
      return target
    },
    onSuccess: (target) => {
      void queryClient.invalidateQueries({ queryKey: ['users'] })
      setDeleting(null)
      toast.success(`${target.email} deleted`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  // The API refuses this anyway; keeping the screen out of reach is clearer
  // than showing it and failing every request.
  if (user && !user.is_superuser) return <Navigate to="/settings/household" replace />

  return (
    <>
      <PageHeader title="Settings" description="Your household, your account." />
      <SettingsNav />

      <Card className="gap-0 py-0">
        <CardHeader className="border-b py-4">
          <CardTitle>All users</CardTitle>
          <CardDescription>
            Every account that can sign in to this deployment. Each has its own household, so no
            figures are shown here.
          </CardDescription>
          <CardAction>
            <Button onClick={() => setCreating(true)}>
              <UserPlus className="size-4" />
              Create an account
            </Button>
          </CardAction>
        </CardHeader>

        {users.isPending ? (
          <CardContent className="py-6">
            <LoadingRows rows={3} />
          </CardContent>
        ) : users.isError ? (
          <CardContent className="py-6">
            <ErrorState error={users.error} />
          </CardContent>
        ) : (
          // Nudged in, so the column headings line up with the card's title
          // rather than sitting eight pixels to its left.
          <div className="px-2 pb-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Person</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Joined</TableHead>
                  <TableHead className="w-10" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {(users.data?.data ?? []).map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium">
                        {row.full_name ?? row.email}
                        {row.is_superuser ? (
                          <Badge variant="secondary" className="gap-1">
                            <ShieldCheck className="size-3" />
                            Superuser
                          </Badge>
                        ) : null}
                        {row.id === user?.id ? <Badge variant="outline">You</Badge> : null}
                      </div>
                      {row.full_name ? (
                        <p className="text-muted-foreground text-xs">{row.email}</p>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      {row.is_active ? (
                        <span className="text-muted-foreground text-sm">Active</span>
                      ) : (
                        <Badge variant="outline">Not verified</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatInstantAsDate(row.created_at)}
                    </TableCell>
                    <TableCell>
                      {row.id === user?.id ? null : (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" aria-label={`Manage ${row.email}`}>
                              <MoreHorizontal className="size-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            <DropdownMenuItem
                              onClick={() =>
                                setActive.mutate({ target: row, active: !row.is_active })
                              }
                            >
                              {row.is_active ? 'Deactivate' : 'Activate'}
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              variant="destructive"
                              disabled={row.is_superuser}
                              onClick={() => setDeleting(row)}
                            >
                              <Trash2 className="size-4" />
                              Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>

      {users.data && users.data.count > 0 ? (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={users.data.count}
          onPageChange={setPage}
          noun="account"
        />
      ) : null}

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Create an account</DialogTitle>
            <DialogDescription>
              It is active straight away and gets its own household, so it needs no email
              verification.
            </DialogDescription>
          </DialogHeader>

          <form
            id="user-form"
            onSubmit={form.handleSubmit((values) => create.mutate(values))}
            className="space-y-4"
            noValidate
          >
            <FormError message={create.isError ? errorMessage(create.error) : null} />

            <Field id="new-name" label="Name" error={form.formState.errors.full_name?.message}>
              {(props) => (
                <Input {...props} {...form.register('full_name')} placeholder="Optional" />
              )}
            </Field>

            <Field id="new-email" label="Email" error={form.formState.errors.email?.message}>
              {(props) => <Input {...props} {...form.register('email')} type="email" />}
            </Field>

            <Field
              id="new-password"
              label="Password"
              hint={PASSWORD_HINT}
              error={form.formState.errors.password?.message}
            >
              {(props) => (
                <Input
                  {...props}
                  {...form.register('password')}
                  type="password"
                  autoComplete="new-password"
                />
              )}
            </Field>
          </form>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreating(false)}>
              Cancel
            </Button>
            <SubmitButton form="user-form" pending={create.isPending}>
              Create account
            </SubmitButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.email}?`}
        description="Their account and their household go with them. This cannot be undone."
        confirmLabel="Delete account"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}
