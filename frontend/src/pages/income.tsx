import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BanknoteArrowUp,
  CalendarClock,
  Lock,
  LockOpen,
  MoreHorizontal,
  Pencil,
  Plus,
  Settings,
  Trash2,
  TriangleAlert,
  UserPlus,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  ForecastBasis,
  householdsUpdateHouseholdMe,
  incomeDeleteClient,
  incomeDeleteSession,
  incomeGetForecast,
  incomeGetSummary,
  incomeListClients,
  incomeListSessions,
  incomeUpdateClient,
  incomeUpdateSession,
  IncomeSessionStatus,
  PaymentStatus,
  type IncomeClientPublic,
  type IncomeSessionPublic,
} from '@/api'
import { IncomeForecastChart } from '@/components/charts/income-forecast-chart'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { ClientDialog } from '@/components/income/client-dialog'
import { ClientName } from '@/components/income/client-name'
import { MonthScopeToggle, type MonthScope } from '@/components/income/month-scope-toggle'
import { PinDialog, type PinMode } from '@/components/income/pin-dialog'
import { EstimateNote } from '@/components/income/estimate-note'
import { SessionDialog } from '@/components/income/session-dialog'
import { PageHeader } from '@/components/layout/page-header'
import { MonthPicker } from '@/components/month-picker'
import { Pagination } from '@/components/pagination'
import { Money } from '@/components/money'
import { StatTile } from '@/components/stat-tile'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuth } from '@/hooks/use-auth'
import { useCurrency, useHousehold, useIsHouseholdOwner } from '@/hooks/use-household'
import { useIncomeClients } from '@/hooks/use-income-clients'
import { useVault } from '@/hooks/use-vault'
import { errorMessage } from '@/lib/api'
import { describeCadence } from '@/lib/cadence'
import { PAYMENT_STATUS_LABELS, SESSION_STATUS_LABELS } from '@/lib/labels'
import { formatPercent } from '@/lib/money'
import { currentMonth, formatDate, formatMonth, shiftMonth } from '@/lib/month'

/** The badge colour each outcome deserves at a glance. */
function statusVariant(status: IncomeSessionStatus) {
  if (status === IncomeSessionStatus.ATTENDED) return 'default' as const
  if (status === IncomeSessionStatus.MISSED) return 'destructive' as const
  return 'secondary' as const
}

function paymentVariant(payment: PaymentStatus) {
  if (payment === PaymentStatus.PAID) return 'default' as const
  if (payment === PaymentStatus.PENDING) return 'destructive' as const
  return 'secondary' as const
}

// Enough rows to be worth reading without pushing the tabs off the screen.
// It is only the starting point: each table offers the choice underneath it.
const DEFAULT_PAGE_SIZE = 20

export function Component() {
  const queryClient = useQueryClient()
  const currency = useCurrency()
  const vault = useVault()
  const household = useHousehold()
  const { user } = useAuth()

  const [month, setMonth] = useState(currentMonth())
  const [showArchived, setShowArchived] = useState(false)
  const [pinMode, setPinMode] = useState<PinMode | null>(null)
  const [editingClient, setEditingClient] = useState<IncomeClientPublic | null>(null)
  const [addingClient, setAddingClient] = useState(false)
  const [editingSession, setEditingSession] = useState<IncomeSessionPublic | null>(null)
  const [addingSession, setAddingSession] = useState(false)
  const [deletingSession, setDeletingSession] = useState<IncomeSessionPublic | null>(null)
  const [deletingClient, setDeletingClient] = useState<IncomeClientPublic | null>(null)
  const [label, setLabel] = useState<string | null>(null)
  // Which month the estimate tile covers. "This" is the default, because at any
  // point in the month the question people actually ask is where they will land
  // by the end of it.
  const [scope, setScope] = useState<MonthScope>('this')

  // Always including the archived ones, because this is the name lookup behind
  // every session row. A debt owed by somebody who stopped coming is the one
  // most worth chasing, and it would otherwise show up with no name against it.
  const clients = useIncomeClients(true)
  const [sessionPage, setSessionPage] = useState(0)
  const [unpaidPage, setUnpaidPage] = useState(0)
  const [clientPage, setClientPage] = useState(0)
  // One setting for all three tables. How many rows you like reading is a
  // preference about you, not about which table you happen to be looking at.
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  // Controlled, because the control that belongs to each tab sits beside the
  // tabs themselves rather than inside the panel below them.
  const [tab, setTab] = useState('sessions')
  // The ledger label lives on the household, and only an owner may change it.
  const isOwner = useIsHouseholdOwner()

  function changePageSize(size: number) {
    setPageSize(size)
    // Page four of twenty rows is not page four of a hundred, so the only
    // honest place to land after the change is the beginning.
    setSessionPage(0)
    setUnpaidPage(0)
    setClientPage(0)
  }

  const summary = useQuery({
    queryKey: ['income-summary', month],
    queryFn: async () => {
      const { data, error } = await incomeGetSummary({ query: { month } })
      if (error) throw error
      return data
    },
  })

  // Both months are fetched rather than one, so the toggle is instant and the
  // chart can show this month and next side by side.
  const thisMonth = currentMonth()
  const nextMonth = shiftMonth(thisMonth, 1)

  function forecastFor(month: string) {
    return {
      queryKey: ['income-forecast', month],
      queryFn: async () => {
        const { data, error } = await incomeGetForecast({ query: { month } })
        if (error) throw error
        return data
      },
    }
  }

  const thisForecast = useQuery(forecastFor(thisMonth))
  const nextForecast = useQuery(forecastFor(nextMonth))
  const forecast = scope === 'this' ? thisForecast : nextForecast
  const forecastMonth = scope === 'this' ? thisMonth : nextMonth

  const sessions = useQuery({
    queryKey: ['income-sessions', { month, page: sessionPage, pageSize }],
    queryFn: async () => {
      const { data, error } = await incomeListSessions({
        query: { month, sort: 'date', skip: sessionPage * pageSize, limit: pageSize },
      })
      if (error) throw error
      return data
    },
  })

  // Every month, oldest first: a debt from March is still a debt in September,
  // so this list is not scoped to the month picker above it.
  const unpaid = useQuery({
    queryKey: ['income-sessions', { unpaid: true, page: unpaidPage, pageSize }],
    queryFn: async () => {
      const { data, error } = await incomeListSessions({
        // `owed_only` is what keeps the diary out of it: a session next
        // Tuesday is unpaid only in the sense that it has not happened yet.
        query: {
          payment_status: PaymentStatus.PENDING,
          owed_only: true,
          sort: 'date',
          skip: unpaidPage * pageSize,
          limit: pageSize,
        },
      })
      if (error) throw error
      return data
    },
  })

  // The Clients tab's own listing, paged by the server like the other two.
  const clientList = useQuery({
    queryKey: ['income-clients', { showArchived, page: clientPage, pageSize }],
    queryFn: async () => {
      const { data, error } = await incomeListClients({
        query: {
          ...(showArchived ? {} : { is_archived: false }),
          skip: clientPage * pageSize,
          limit: pageSize,
        },
      })
      if (error) throw error
      return data
    },
  })

  function invalidate() {
    for (const key of [
      ['income-sessions'],
      ['income-summary'],
      ['income-forecast'],
      ['income-clients'],
      // A paid session writes to the ledger and moves an account balance.
      ['transactions'],
      ['accounts'],
      ['reports'],
    ]) {
      void queryClient.invalidateQueries({ queryKey: key })
    }
  }

  const setPayment = useMutation({
    mutationFn: async ({
      session,
      payment,
    }: {
      session: IncomeSessionPublic
      payment: PaymentStatus
    }) => {
      const { error } = await incomeUpdateSession({
        path: { session_id: session.id },
        body: {
          payment_status: payment,
          // Paid today, not on the day of the hour: this button is pressed when
          // the money actually turns up.
          paid_on: payment === PaymentStatus.PAID ? new Date().toISOString().slice(0, 10) : null,
        },
      })
      if (error) throw error
    },
    onSuccess: () => {
      invalidate()
      toast.success('Session updated')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const setStatus = useMutation({
    mutationFn: async ({
      session,
      status,
    }: {
      session: IncomeSessionPublic
      status: IncomeSessionStatus
    }) => {
      const { error } = await incomeUpdateSession({
        path: { session_id: session.id },
        body: { status },
      })
      if (error) throw error
    },
    onSuccess: () => {
      invalidate()
      toast.success('Session updated')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const removeSession = useMutation({
    mutationFn: async (session: IncomeSessionPublic) => {
      const { error } = await incomeDeleteSession({ path: { session_id: session.id } })
      if (error) throw error
    },
    onSuccess: () => {
      invalidate()
      setDeletingSession(null)
      toast.success('Session deleted')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const removeClient = useMutation({
    mutationFn: async (client: IncomeClientPublic) => {
      const { error } = await incomeDeleteClient({ path: { client_id: client.id } })
      if (error) throw error
    },
    onSuccess: () => {
      invalidate()
      setDeletingClient(null)
      toast.success('Client deleted')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const archiveClient = useMutation({
    mutationFn: async ({ client, archived }: { client: IncomeClientPublic; archived: boolean }) => {
      const { error } = await incomeUpdateClient({
        path: { client_id: client.id },
        body: { is_archived: archived },
      })
      if (error) throw error
    },
    onSuccess: () => {
      invalidate()
      toast.success('Client updated')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const saveLabel = useMutation({
    mutationFn: async (value: string) => {
      const { error } = await householdsUpdateHouseholdMe({
        body: { session_merchant_label: value },
      })
      if (error) throw error
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['household'] })
      setLabel(null)
      toast.success('Label saved')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const rows = sessions.data?.data ?? []
  const unpaidRows = unpaid.data?.data ?? []
  // Everything owed, not the rows on this page. The badge is a count of debts
  // to chase, and paging through them does not make the rest go away.
  const unpaidTotal = unpaid.data?.count ?? 0
  // Two different jobs, so two different reads. This one is the lookup behind
  // every session row's name and behind the pickers in the dialogs, so it
  // walks to the end of the list rather than stopping at a page: a name is not
  // optional because its client sits on page two.
  const byId = new Map((clients.data?.data ?? []).map((one) => [one.id, one]))
  const clientsOnPage = clientList.data?.data ?? []
  const forecastRows = forecast.data?.clients ?? []
  const tallyById = new Map(forecastRows.map((one) => [one.client_id, one]))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Income"
        description="The people you see, what they owe, and what next month is likely to bring."
      >
        {/* Left out rather than disabled for a member who is not an owner:
            the household refuses the change, and a control that is there to be
            filled in and then refused is worse than one that is not there. */}
        {isOwner ? (
          <Popover
            open={label !== null}
            onOpenChange={(open) =>
              setLabel(open ? (household.data?.session_merchant_label ?? 'Session') : null)
            }
          >
            <PopoverTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Ledger label">
                <Settings className="size-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 space-y-3">
              <div className="space-y-1">
                <Label htmlFor="session-label">Ledger label</Label>
                <p className="text-muted-foreground text-xs">
                  What paid sessions are called on the Transactions page. Client names never appear
                  there.
                </p>
              </div>
              <Input
                id="session-label"
                value={label ?? ''}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="Session"
              />
              <Button
                size="sm"
                className="w-full"
                disabled={!label?.trim() || saveLabel.isPending}
                onClick={() => label && saveLabel.mutate(label.trim())}
              >
                Save
              </Button>
            </PopoverContent>
          </Popover>
        ) : null}

        {vault.status === 'absent' ? (
          <Button variant="outline" onClick={() => setPinMode('set-up')}>
            <Lock className="size-4" />
            Set a PIN
          </Button>
        ) : vault.status === 'unlocked' ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline">
                <LockOpen className="size-4" />
                Names visible
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => vault.lock()}>Lock names</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setPinMode('change')}>
                Change the PIN
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : (
          <Button
            variant="outline"
            onClick={() => setPinMode('unlock')}
            disabled={vault.status === 'loading'}
          >
            <Lock className="size-4" />
            Unlock names
          </Button>
        )}

        <Button
          variant="outline"
          onClick={() => setAddingClient(true)}
          disabled={vault.status !== 'unlocked'}
        >
          <UserPlus className="size-4" />
          Add client
        </Button>
        <Button onClick={() => setAddingSession(true)} disabled={byId.size === 0}>
          <Plus className="size-4" />
          Log session
        </Button>
      </PageHeader>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label={`Earned in ${formatMonth(month, { month: 'long' })}`}
          minor={summary.data?.earned_minor ?? 0}
          currency={currency}
          hint={
            summary.data && summary.data.outstanding_minor > 0 ? (
              <>
                <Money minor={summary.data.outstanding_minor} currency={currency} /> of it still
                unpaid
              </>
            ) : (
              `${summary.data?.attended_count ?? 0} sessions`
            )
          }
        />
        <StatTile
          label="Owed to you"
          minor={summary.data?.total_outstanding_minor ?? 0}
          currency={currency}
          tone={summary.data && summary.data.total_outstanding_minor > 0 ? 'negative' : undefined}
          hint={
            summary.data?.oldest_unpaid_on
              ? `Oldest from ${formatDate(summary.data.oldest_unpaid_on)}`
              : 'Everybody has paid'
          }
        />
        <StatTile
          label={`Earned in ${summary.data?.year ?? new Date().getFullYear()}`}
          minor={summary.data?.year_earned_minor ?? 0}
          currency={currency}
          hint={`${summary.data?.year_session_count ?? 0} sessions so far`}
        />
        <StatTile
          label={`Expected in ${formatMonth(forecastMonth, { month: 'long' })}`}
          minor={forecast.data?.likely_minor ?? 0}
          currency={currency}
          action={<MonthScopeToggle value={scope} onChange={setScope} />}
          hint={
            forecast.data && forecast.data.high_minor > forecast.data.low_minor ? (
              <>
                <Money minor={forecast.data.low_minor} currency={currency} /> to{' '}
                <Money minor={forecast.data.high_minor} currency={currency} />
              </>
            ) : (
              'Not enough history yet'
            )
          }
        />
      </div>

      {clients.data && !clients.data.isComplete ? (
        <Alert>
          <TriangleAlert className="size-4" />
          <AlertTitle>Some names could not be loaded</AlertTitle>
          <AlertDescription>
            There are more clients than this page reads in one go, so a few sessions may show no
            name against them. Every figure is still correct.
          </AlertDescription>
        </Alert>
      ) : null}

      {forecast.data && forecast.data.basis !== ForecastBasis.HISTORY ? (
        <Alert>
          <CalendarClock className="size-4" />
          <AlertTitle>The estimate is still settling</AlertTitle>
          <AlertDescription>
            It is built from {forecast.data.months_used === 0 ? 'no' : forecast.data.months_used}{' '}
            complete {forecast.data.months_used === 1 ? 'month' : 'months'}. After three months it
            starts to mean something.
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Where the months are landing</CardTitle>
        </CardHeader>
        <CardContent>
          {forecast.isPending ? (
            <LoadingRows />
          ) : forecast.isError ? (
            <ErrorState error={forecast.error} />
          ) : thisForecast.data && nextForecast.data ? (
            <IncomeForecastChart
              forecast={thisForecast.data}
              next={nextForecast.data}
              currency={currency}
              totalOutstandingMinor={summary.data?.total_outstanding_minor}
            />
          ) : null}
        </CardContent>
        {forecast.data ? (
          <CardFooter>
            <EstimateNote forecast={forecast.data} currency={currency} />
          </CardFooter>
        ) : null}
      </Card>

      <Tabs value={tab} onValueChange={setTab}>
        {/* One row: which table, and the one control that table needs. They
            belong together, and stacking them wasted a line of the page on a
            control that is often not even there. */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          {/* Roomier than the default: three words shoulder to shoulder read
              as one crowded block, and one of them carries a count. */}
          <TabsList className="[&>button]:px-3.5">
            <TabsTrigger value="sessions">Sessions</TabsTrigger>
            <TabsTrigger value="unpaid">
              Unpaid
              {unpaidTotal > 0 ? (
                // No margin of its own. The trigger's own gap is smaller than
                // the space between two tabs, which is what makes the count
                // read as belonging to this word rather than floating between
                // it and the next one.
                <Badge variant="destructive" className="px-1.5 py-0 text-[11px] tabular-nums">
                  {unpaidTotal}
                </Badge>
              ) : null}
            </TabsTrigger>
            <TabsTrigger value="clients">Clients</TabsTrigger>
          </TabsList>

          {tab === 'sessions' ? (
            <MonthPicker
              month={month}
              onChange={(next) => {
                setMonth(next)
                // Page 3 of August is not page 3 of September.
                setSessionPage(0)
              }}
            />
          ) : null}

          {tab === 'clients' ? (
            <div className="flex items-center gap-2">
              <Switch
                id="show-archived"
                checked={showArchived}
                onCheckedChange={(next) => {
                  setShowArchived(next)
                  setClientPage(0)
                }}
              />
              <Label htmlFor="show-archived">Show archived</Label>
            </div>
          ) : null}
        </div>

        <TabsContent value="sessions" className="space-y-4">
          {sessions.isPending ? (
            <LoadingRows />
          ) : sessions.isError ? (
            <ErrorState error={sessions.error} />
          ) : rows.length === 0 ? (
            <EmptyState
              icon={CalendarClock}
              title="No sessions this month"
              description="Log the hours you worked and mark them paid as the money comes in."
            />
          ) : (
            <Card className="overflow-hidden py-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Day</TableHead>
                      <TableHead>Client</TableHead>
                      <TableHead className="text-right">Fee</TableHead>
                      <TableHead>Session</TableHead>
                      <TableHead>Money</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((session) => (
                      <SessionRow
                        key={session.id}
                        session={session}
                        nameCt={byId.get(session.client_id)?.name_ct}
                        ownerUserId={byId.get(session.client_id)?.owner_user_id}
                        currency={currency}
                        onEdit={() => setEditingSession(session)}
                        onDelete={() => setDeletingSession(session)}
                        onStatus={(status) => setStatus.mutate({ session, status })}
                        onPayment={(payment) => setPayment.mutate({ session, payment })}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}

          {sessions.data ? (
            <Pagination
              page={sessionPage}
              pageSize={pageSize}
              total={sessions.data.count}
              onPageChange={setSessionPage}
              onPageSizeChange={changePageSize}
              noun="session"
              id="session"
            />
          ) : null}
        </TabsContent>

        <TabsContent value="unpaid" className="space-y-4">
          {unpaid.isPending ? (
            <LoadingRows />
          ) : unpaid.isError ? (
            <ErrorState error={unpaid.error} />
          ) : unpaidRows.length === 0 ? (
            <EmptyState
              icon={BanknoteArrowUp}
              title="Nobody owes you anything"
              description="Every session that happened has been settled."
            />
          ) : (
            <Card className="overflow-hidden py-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Day</TableHead>
                      <TableHead>Client</TableHead>
                      <TableHead className="text-right">Owed</TableHead>
                      <TableHead>Session</TableHead>
                      <TableHead className="w-32" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {unpaidRows.map((session) => (
                      <TableRow key={session.id}>
                        <TableCell className="whitespace-nowrap">
                          {formatDate(session.occurs_on)}
                        </TableCell>
                        <TableCell>
                          {byId.get(session.client_id) ? (
                            <ClientName
                              nameCt={byId.get(session.client_id)!.name_ct}
                              ownerUserId={byId.get(session.client_id)!.owner_user_id}
                            />
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          <Money minor={session.fee_minor} currency={currency} />
                        </TableCell>
                        <TableCell>
                          <Badge variant={statusVariant(session.status)}>
                            {SESSION_STATUS_LABELS[session.status]}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() =>
                              setPayment.mutate({ session, payment: PaymentStatus.PAID })
                            }
                          >
                            Mark paid
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}

          {unpaid.data ? (
            <Pagination
              page={unpaidPage}
              pageSize={pageSize}
              total={unpaid.data.count}
              onPageChange={setUnpaidPage}
              onPageSizeChange={changePageSize}
              noun="unpaid session"
              id="unpaid-session"
            />
          ) : null}
        </TabsContent>

        <TabsContent value="clients" className="space-y-4">
          {clientList.isPending ? (
            <LoadingRows />
          ) : clientList.isError ? (
            <ErrorState error={clientList.error} />
          ) : clientsOnPage.length === 0 ? (
            <EmptyState
              icon={UserPlus}
              title="No clients yet"
              description="Add the people you see. Their names are scrambled on this device under your own PIN, so nobody else in the household can read them."
            >
              <Button onClick={() => setPinMode(vault.status === 'absent' ? 'set-up' : 'unlock')}>
                {vault.status === 'absent' ? 'Set a PIN to start' : 'Unlock to add clients'}
              </Button>
            </EmptyState>
          ) : (
            <Card className="overflow-hidden py-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Client</TableHead>
                      <TableHead>Seen</TableHead>
                      <TableHead className="text-right">Usual fee</TableHead>
                      <TableHead className="text-right">Attendance</TableHead>
                      <TableHead className="text-right">Owed</TableHead>
                      <TableHead>Last session</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {clientsOnPage.map((client) => {
                      const tally = tallyById.get(client.id)
                      // A client belongs to whoever added them. The household
                      // shares the money, not the practice.
                      const isMine = client.owner_user_id === user?.id
                      return (
                        <TableRow key={client.id}>
                          <TableCell>
                            <ClientName
                              nameCt={client.name_ct}
                              ownerUserId={client.owner_user_id}
                            />
                            {!isMine ? (
                              <Badge variant="outline" className="ml-2">
                                Not yours
                              </Badge>
                            ) : null}
                            {client.archived_at ? (
                              <Badge variant="secondary" className="ml-2">
                                Archived
                              </Badge>
                            ) : null}
                          </TableCell>
                          <TableCell className="whitespace-nowrap">
                            {client.cadence_frequency ? (
                              describeCadence(
                                client.cadence_frequency,
                                client.cadence_interval,
                                client.cadence_anchor_on,
                                client.cadence_weekdays,
                              )
                            ) : (
                              <span className="text-muted-foreground">As and when</span>
                            )}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            <Money minor={client.default_rate_minor} currency={currency} />
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {/* An em dash, never 0%: a client nobody has seen
                                yet has not been unreliable. */}
                            {tally?.attendance_rate != null
                              ? formatPercent(tally.attendance_rate)
                              : '—'}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {tally && tally.outstanding_minor > 0 ? (
                              <Money minor={tally.outstanding_minor} currency={currency} />
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                          <TableCell className="whitespace-nowrap">
                            {tally?.last_session_on ? formatDate(tally.last_session_on) : '—'}
                          </TableCell>
                          <TableCell>
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon" aria-label="Client actions">
                                  <MoreHorizontal className="size-4" />
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                <DropdownMenuItem
                                  onSelect={() => setEditingClient(client)}
                                  disabled={!isMine || vault.status !== 'unlocked'}
                                >
                                  <Pencil className="size-4" />
                                  Edit
                                </DropdownMenuItem>
                                {/* A client belongs to whoever added them, and
                                    the API refuses all three of these to
                                    anybody else. Edit was already disabled;
                                    these two would only produce a 403. */}
                                <DropdownMenuItem
                                  disabled={!isMine}
                                  onSelect={() =>
                                    archiveClient.mutate({
                                      client,
                                      archived: client.archived_at === null,
                                    })
                                  }
                                >
                                  {client.archived_at ? 'Bring back' : 'Archive'}
                                </DropdownMenuItem>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem
                                  variant="destructive"
                                  disabled={!isMine}
                                  onSelect={() => setDeletingClient(client)}
                                >
                                  <Trash2 className="size-4" />
                                  Delete
                                </DropdownMenuItem>
                              </DropdownMenuContent>
                            </DropdownMenu>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}

          {clientList.data ? (
            <Pagination
              page={clientPage}
              pageSize={pageSize}
              total={clientList.data.count}
              onPageChange={setClientPage}
              onPageSizeChange={changePageSize}
              noun="client"
              id="client"
            />
          ) : null}
        </TabsContent>
      </Tabs>

      <PinDialog
        open={pinMode !== null}
        mode={pinMode ?? 'unlock'}
        onOpenChange={() => setPinMode(null)}
      />

      <ClientDialog
        open={addingClient || editingClient !== null}
        client={editingClient}
        onOpenChange={(open) => {
          if (!open) {
            setAddingClient(false)
            setEditingClient(null)
          }
        }}
      />

      <SessionDialog
        open={addingSession || editingSession !== null}
        session={editingSession}
        onOpenChange={(open) => {
          if (!open) {
            setAddingSession(false)
            setEditingSession(null)
          }
        }}
      />

      <ConfirmDialog
        open={deletingSession !== null}
        onOpenChange={(open) => !open && setDeletingSession(null)}
        title="Delete this session?"
        description="If it was paid, the income it put in your ledger goes with it."
        confirmLabel="Delete"
        pending={removeSession.isPending}
        onConfirm={() => deletingSession && removeSession.mutate(deletingSession)}
      />

      <ConfirmDialog
        open={deletingClient !== null}
        onOpenChange={(open) => !open && setDeletingClient(null)}
        title="Delete this client?"
        description="Only a client with no sessions can be deleted. Archive them instead to keep the record."
        confirmLabel="Delete"
        pending={removeClient.isPending}
        onConfirm={() => deletingClient && removeClient.mutate(deletingClient)}
      />
    </div>
  )
}

/** One session in the month table, with both of its facts shown apart. */
function SessionRow({
  session,
  nameCt,
  ownerUserId,
  currency,
  onEdit,
  onDelete,
  onStatus,
  onPayment,
}: {
  session: IncomeSessionPublic
  nameCt: string | undefined
  ownerUserId: string | undefined
  currency: string
  onEdit: () => void
  onDelete: () => void
  onStatus: (status: IncomeSessionStatus) => void
  onPayment: (payment: PaymentStatus) => void
}) {
  return (
    <TableRow>
      <TableCell className="whitespace-nowrap">{formatDate(session.occurs_on)}</TableCell>
      <TableCell>
        {nameCt ? (
          <ClientName nameCt={nameCt} ownerUserId={ownerUserId} />
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="text-right tabular-nums">
        <Money minor={session.fee_minor} currency={currency} />
      </TableCell>
      <TableCell>
        <Badge variant={statusVariant(session.status)}>
          {SESSION_STATUS_LABELS[session.status]}
        </Badge>
      </TableCell>
      <TableCell>
        {/* Two badges, never one. "Attended" and "Unpaid" are both true at
            once, and a merged badge would have to drop one of them. */}
        <Badge variant={paymentVariant(session.payment_status)}>
          {PAYMENT_STATUS_LABELS[session.payment_status]}
        </Badge>
      </TableCell>
      <TableCell>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Session actions">
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>What happened</DropdownMenuLabel>
            {Object.values(IncomeSessionStatus).map((value) => (
              <DropdownMenuItem
                key={value}
                disabled={session.status === value}
                onSelect={() => onStatus(value)}
              >
                {SESSION_STATUS_LABELS[value]}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuLabel>The money</DropdownMenuLabel>
            {Object.values(PaymentStatus).map((value) => (
              <DropdownMenuItem
                key={value}
                disabled={session.payment_status === value}
                onSelect={() => onPayment(value)}
              >
                {PAYMENT_STATUS_LABELS[value]}
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={onEdit}>
              <Pencil className="size-4" />
              Edit
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={onDelete}>
              <Trash2 className="size-4" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
    </TableRow>
  )
}
