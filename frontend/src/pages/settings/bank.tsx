import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Landmark, Loader2, RefreshCw, Unplug } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'

import {
  type AccountPublic,
  type BankAccountPublic,
  type BankAccountUpdate,
  type BankConnectionPublic,
  BankConnectionStatus,
  type BankSyncRunPublic,
  BankSyncStatus,
  bankDisconnectBank,
  bankListAspsps,
  bankStartBankConnection,
  bankSyncBankConnection,
  bankUpdateBankAccount,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { Field } from '@/components/form-field'
import { PageHeader } from '@/components/layout/page-header'
import { SettingsNav } from '@/components/layout/settings-nav'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAccounts } from '@/hooks/use-accounts'
import { useAuth } from '@/hooks/use-auth'
import { useBankConnections, useBankStatus } from '@/hooks/use-bank'
import { useIsHouseholdOwner } from '@/hooks/use-household'
import { errorMessage } from '@/lib/api'
import { useLocale } from '@/lib/locale-context'
import { formatDateTime, formatInstantAsDate, today } from '@/lib/month'

const NOT_LINKED = 'none'

/**
 * The countries the bank provider reaches: the EEA and the UK.
 *
 * Kept here rather than asked for, because the provider has no endpoint that
 * lists them, and the list changes about as often as the EEA does.
 */
const COUNTRIES = [
  'AT', 'BE', 'BG', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GB', 'GR', 'HR', 'HU',
  'IE', 'IS', 'IT', 'LI', 'LT', 'LU', 'LV', 'MT', 'NL', 'NO', 'PL', 'PT', 'RO', 'SE', 'SI', 'SK',
] // prettier-ignore

export function Component() {
  const status = useBankStatus()
  const enabled = status.data?.enabled ?? false
  const connections = useBankConnections({ enabled })
  const linkedAccountIds = (connections.data?.data ?? []).flatMap((connection) =>
    connection.accounts.flatMap((bankAccount) =>
      bankAccount.account_id ? [bankAccount.account_id] : [],
    ),
  )

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Banks that send their transactions to your inbox, for you to accept or skip."
      />
      <SettingsNav />

      {status.isPending ? (
        <LoadingRows rows={2} />
      ) : status.isError ? (
        <ErrorState error={status.error} />
      ) : !enabled ? (
        <EmptyState
          icon={Landmark}
          title="Bank sync is off"
          description="This server is not registered with a bank provider. Whoever runs hydra can turn it on."
        />
      ) : (
        <>
          <ConnectCard />

          {connections.isPending ? (
            <LoadingRows rows={2} />
          ) : connections.isError ? (
            <ErrorState error={connections.error} />
          ) : connections.data.count === 0 ? (
            <EmptyState
              icon={Landmark}
              title="No banks yet"
              description="Connect one above. You log in at your bank, and hydra never sees your password."
            />
          ) : (
            connections.data.data.map((connection) => (
              <ConnectionCard
                key={connection.id}
                connection={connection}
                linkedAccountIds={linkedAccountIds}
              />
            ))
          )}
        </>
      )}
    </div>
  )
}

/** The region a locale names, when it is one the provider reaches. */
function defaultCountry(locale: string | undefined): string {
  try {
    const region = new Intl.Locale(locale ?? navigator.language).maximize().region
    return region && COUNTRIES.includes(region) ? region : ''
  } catch {
    return ''
  }
}

/**
 * Send the browser to the bank's login.
 *
 * The bank sends it back to the callback page, which finishes the job. Shared
 * by a first connection and by renewing one that expired.
 */
function useStartConnection() {
  return useMutation({
    mutationFn: async (bank: { name: string; country: string }) => {
      const { data, error } = await bankStartBankConnection({
        body: { aspsp_name: bank.name, aspsp_country: bank.country },
      })
      if (error || !data) throw error ?? new Error('The bank could not be reached.')
      return data
    },
    onSuccess: ({ url }) => window.location.assign(url),
    onError: (error) => toast.error(errorMessage(error)),
  })
}

function ConnectCard() {
  const locale = useLocale()
  const [country, setCountry] = useState(() => defaultCountry(locale))
  const [bank, setBank] = useState('')
  const start = useStartConnection()

  const names = new Intl.DisplayNames(locale ? [locale] : undefined, { type: 'region' })
  const countries = COUNTRIES.map((code) => ({ code, name: names.of(code) ?? code })).sort((a, b) =>
    a.name.localeCompare(b.name, locale),
  )

  const banks = useQuery({
    queryKey: ['bank', 'aspsps', country],
    enabled: country !== '',
    queryFn: async () => {
      const { data, error } = await bankListAspsps({ query: { country } })
      if (error || !data) throw error ?? new Error('Could not load the banks.')
      return data
    },
    staleTime: 60 * 60_000,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect a bank</CardTitle>
        <CardDescription>
          You log in at your bank and say which accounts hydra may read. It can read them for about
          six months, then asks you to log in again. It can never move money.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-wrap items-start gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            if (bank) start.mutate({ name: bank, country })
          }}
        >
          <Field id="bank-country" label="Country" className="w-56">
            {(props) => (
              <Select
                value={country}
                onValueChange={(value) => {
                  setCountry(value)
                  setBank('')
                }}
              >
                <SelectTrigger id={props.id} className="w-56">
                  <SelectValue placeholder="Choose a country" />
                </SelectTrigger>
                <SelectContent>
                  {countries.map((item) => (
                    <SelectItem key={item.code} value={item.code}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Field
            id="bank-name"
            label="Bank"
            className="min-w-64 flex-1"
            error={banks.isError ? errorMessage(banks.error) : undefined}
          >
            {(props) => (
              <Select
                value={bank}
                onValueChange={setBank}
                disabled={!country || banks.isPending || banks.isError}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue
                    placeholder={country && banks.isPending ? 'Loading banks…' : 'Choose a bank'}
                  />
                </SelectTrigger>
                <SelectContent>
                  {(banks.data?.data ?? []).map((item) => (
                    <SelectItem key={item.name} value={item.name}>
                      {item.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          <Button type="submit" className="mt-6" disabled={!bank || start.isPending}>
            {start.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
            Connect
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

/** What a sync did, said in a toast. */
function reportSync(run: BankSyncRunPublic, openInbox: () => void) {
  if (run.status === BankSyncStatus.FAILED) {
    toast.error(run.error ?? 'The sync failed.')
    return
  }
  if (run.new_count === 0) {
    toast.success('Synced. Nothing new.')
    return
  }
  toast.success(
    run.new_count === 1
      ? '1 new transaction in your inbox'
      : `${run.new_count} new transactions in your inbox`,
    { action: { label: 'Review', onClick: openInbox } },
  )
}

function ConnectionCard({
  connection,
  linkedAccountIds,
}: {
  connection: BankConnectionPublic
  /** Every Hydra account a bank account feeds, across all the connections. */
  linkedAccountIds: string[]
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isOwner = useIsHouseholdOwner()
  const [disconnecting, setDisconnecting] = useState(false)
  const renew = useStartConnection()
  const isActive = connection.status === BankConnectionStatus.ACTIVE
  // The API refuses anyone else, so the button is not offered to them.
  const canDisconnect = isOwner || connection.created_by_user_id === user?.id

  const sync = useMutation({
    mutationFn: async () => {
      const { data, error } = await bankSyncBankConnection({
        path: { connection_id: connection.id },
      })
      if (error || !data) throw error ?? new Error('The sync failed.')
      return data
    },
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ['bank'] })
      reportSync(run, () => void navigate('/inbox'))
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const disconnect = useMutation({
    mutationFn: async () => {
      const { error } = await bankDisconnectBank({ path: { connection_id: connection.id } })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bank', 'connections'] })
      setDisconnecting(false)
      toast.success(`${connection.aspsp_name} disconnected`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            {connection.aspsp_name}
            {isActive ? null : <Badge variant="destructive">Expired</Badge>}
          </CardTitle>
          <CardDescription>
            {isActive && connection.valid_until
              ? `Access until ${formatInstantAsDate(connection.valid_until)}. `
              : isActive
                ? ''
                : 'Log in at your bank again to keep it syncing. '}
            {connection.last_synced_at
              ? `Last synced ${formatDateTime(connection.last_synced_at)}.`
              : 'Not synced yet.'}
          </CardDescription>
          {connection.last_sync_error ? (
            <p className="text-destructive text-sm">{connection.last_sync_error}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {isActive ? (
            <Button variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}>
              {sync.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <RefreshCw className="size-4" />
              )}
              Sync now
            </Button>
          ) : (
            <Button
              onClick={() =>
                renew.mutate({ name: connection.aspsp_name, country: connection.aspsp_country })
              }
              disabled={renew.isPending}
            >
              {renew.isPending ? <Loader2 className="size-4 animate-spin" /> : null}
              Log in again
            </Button>
          )}
          {canDisconnect ? (
            <Button variant="ghost" onClick={() => setDisconnecting(true)}>
              <Unplug className="size-4" />
              Disconnect
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent>
        {connection.accounts.length === 0 ? (
          <p className="text-muted-foreground text-sm">The login reached no accounts.</p>
        ) : (
          <div className="overflow-x-auto">
            <Table className="min-w-[48rem]">
              <TableHeader>
                <TableRow>
                  <TableHead>Bank account</TableHead>
                  <TableHead className="w-60">Goes into</TableHead>
                  <TableHead className="w-44">Import from</TableHead>
                  <TableHead className="w-20">Sync</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {connection.accounts.map((bankAccount) => (
                  <BankAccountRow
                    key={bankAccount.id}
                    bankAccount={bankAccount}
                    linkedAccountIds={linkedAccountIds}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      <ConfirmDialog
        open={disconnecting}
        onOpenChange={setDisconnecting}
        title={`Disconnect ${connection.aspsp_name}?`}
        description="hydra stops reading it, and the bank is told to end the access. What is already in your inbox and your ledger stays."
        confirmLabel="Disconnect"
        onConfirm={() => disconnect.mutate()}
        pending={disconnect.isPending}
      />
    </Card>
  )
}

/** How an account reads in the picker. */
function accountLabel(account: AccountPublic) {
  return `${account.name} (${account.currency_code})`
}

function BankAccountRow({
  bankAccount,
  linkedAccountIds,
}: {
  bankAccount: BankAccountPublic
  linkedAccountIds: string[]
}) {
  const queryClient = useQueryClient()
  const accounts = useAccounts()
  const linked = (accounts.data?.data ?? []).find((a) => a.id === bankAccount.account_id)

  // One Hydra account takes one bank's rows, in the bank's own currency. The
  // API refuses anything else, so the picker does not offer it.
  const options = (accounts.data?.data ?? []).filter(
    (account) =>
      account.id === bankAccount.account_id ||
      (!linkedAccountIds.includes(account.id) &&
        (!bankAccount.currency_code || account.currency_code === bankAccount.currency_code)),
  )

  const update = useMutation({
    mutationFn: async (body: BankAccountUpdate) => {
      const { data, error } = await bankUpdateBankAccount({
        path: { bank_account_id: bankAccount.id },
        body,
      })
      if (error || !data) throw error ?? new Error('Could not save the change.')
      return data
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['bank', 'connections'] }),
    onError: (error) => toast.error(errorMessage(error)),
  })

  const label = bankAccount.name ?? bankAccount.iban ?? 'Bank account'

  return (
    <TableRow>
      <TableCell>
        <div className="font-medium">{label}</div>
        <div className="text-muted-foreground text-xs">
          {[bankAccount.iban, bankAccount.currency_code].filter(Boolean).join(' · ')}
        </div>
      </TableCell>
      <TableCell>
        <Select
          value={bankAccount.account_id ?? NOT_LINKED}
          onValueChange={(value) =>
            update.mutate({ account_id: value === NOT_LINKED ? null : value })
          }
          disabled={update.isPending || accounts.isError}
        >
          <SelectTrigger className="w-56" aria-label={`Hydra account for ${label}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NOT_LINKED}>Not linked</SelectItem>
            {options.map((account) => (
              <SelectItem key={account.id} value={account.id}>
                {accountLabel(account)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </TableCell>
      <TableCell>
        {bankAccount.account_id ? (
          <Input
            // Keyed on the saved value, so a refused date snaps back to it.
            key={bankAccount.import_from ?? ''}
            type="date"
            aria-label={`Import ${label} from`}
            defaultValue={bankAccount.import_from ?? ''}
            min={linked?.opening_balance_date}
            max={today()}
            className="w-40"
            disabled={update.isPending}
            // On blur rather than on change: a date typed digit by digit is
            // a valid but wrong date several times on the way.
            onBlur={(event) => {
              const value = event.currentTarget.value
              if (value && value !== bankAccount.import_from) update.mutate({ import_from: value })
            }}
          />
        ) : (
          <span className="text-muted-foreground text-sm">Link it first</span>
        )}
      </TableCell>
      <TableCell>
        {/* An account with nowhere to go is never synced, so the switch only
            means something once it is linked. */}
        <Switch
          checked={bankAccount.sync_enabled && Boolean(bankAccount.account_id)}
          onCheckedChange={(checked) => update.mutate({ sync_enabled: checked })}
          disabled={update.isPending || !bankAccount.account_id}
          aria-label={`Sync ${label}`}
        />
      </TableCell>
    </TableRow>
  )
}
