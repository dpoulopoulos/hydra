import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Tag,
  Trash2,
  TrendingUp,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  investmentsDeleteInstrument,
  investmentsDeleteTrade,
  investmentsGetPortfolio,
  investmentsListFxRates,
  investmentsListTrades,
  investmentsRefreshPrices,
  InstrumentKind,
  type InstrumentPublic,
  type PositionPublic,
  type TradePublic,
} from '@/api'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { InstrumentDialog } from '@/components/investments/instrument-dialog'
import { TradeDialog } from '@/components/investments/trade-dialog'
import { PriceDialog } from '@/components/investments/price-dialog'
import { PageHeader } from '@/components/layout/page-header'
import { Money } from '@/components/money'
import { StatTile } from '@/components/stat-tile'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Label } from '@/components/ui/label'
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
import { useInstruments } from '@/hooks/use-instruments'
import { errorMessage } from '@/lib/api'
import { INSTRUMENT_KIND_LABELS, TRADE_SIDE_LABELS } from '@/lib/labels'
import { formatDate, formatDateTime } from '@/lib/month'
import { useLocale } from '@/lib/locale-context'
import { formatPrice, formatQuantity, formatRate, MICRO } from '@/lib/quantity'

const TRADE_PAGE_SIZE = 25

export function Component() {
  const queryClient = useQueryClient()
  const locale = useLocale()
  const [includeClosed, setIncludeClosed] = useState(false)
  const [addingInstrument, setAddingInstrument] = useState(false)
  const [editingInstrument, setEditingInstrument] = useState<InstrumentPublic | null>(null)
  const [tradingInstrumentId, setTradingInstrumentId] = useState<string | null>(null)
  const [recordingTrade, setRecordingTrade] = useState(false)
  const [deletingPosition, setDeletingPosition] = useState<PositionPublic | null>(null)
  const [deletingInstrument, setDeletingInstrument] = useState<InstrumentPublic | null>(null)
  const [pricingInstrument, setPricingInstrument] = useState<InstrumentPublic | null>(null)
  const [deletingTrade, setDeletingTrade] = useState<TradePublic | null>(null)

  const instruments = useInstruments()

  const portfolio = useQuery({
    queryKey: ['portfolio', { includeClosed }],
    queryFn: async () => {
      const { data, error } = await investmentsGetPortfolio({
        query: { include_closed: includeClosed },
      })
      if (error) throw error
      return data
    },
  })

  const trades = useQuery({
    queryKey: ['trades'],
    queryFn: async () => {
      const { data, error } = await investmentsListTrades({ query: { limit: TRADE_PAGE_SIZE } })
      if (error) throw error
      return data
    },
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['portfolio'] })
    void queryClient.invalidateQueries({ queryKey: ['trades'] })
    void queryClient.invalidateQueries({ queryKey: ['instruments'] })
    void queryClient.invalidateQueries({ queryKey: ['fx-rates'] })
  }

  // Read-only and never fetched from the provider, so opening this costs
  // nothing out of the daily API budget.
  const fxRates = useQuery({
    queryKey: ['fx-rates'],
    queryFn: async () => {
      const { data, error } = await investmentsListFxRates()
      if (error) throw error
      return data
    },
    staleTime: 60_000,
  })

  const refresh = useMutation({
    mutationFn: async () => {
      const { data, error } = await investmentsRefreshPrices()
      if (error) throw error
      return data
    },
    onSuccess: (result) => {
      invalidate()

      const failures = result?.failures ?? []
      const updated = result?.updated_count ?? 0
      const cached = result?.cached_count ?? 0

      // Both halves of the outcome are reported, because "12 priced" alone
      // would hide the one holding that is now quietly out of date.
      if (failures.length > 0) {
        toast.warning(
          `${updated} priced, ${failures.length} could not be: ` +
            failures.map((failure) => failure.symbol).join(', '),
        )
      } else if (updated === 0 && cached > 0) {
        // Said plainly rather than dressed up as a refresh. The provider bills
        // one call per holding out of twenty a day, so a press that spent
        // nothing is the good outcome and worth naming.
        toast.info(`Already up to date, so nothing was fetched`)
      } else if (updated === 0) {
        toast.info('Nothing to price yet')
      } else if (cached > 0) {
        toast.success(`${updated} priced, ${cached} already up to date`)
      } else {
        toast.success(`${updated} priced`)
      }
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const removeInstrument = useMutation({
    mutationFn: async (position: PositionPublic) => {
      const { error } = await investmentsDeleteInstrument({
        path: { instrument_id: position.instrument_id },
      })
      if (error) throw error
      return position
    },
    onSuccess: (position) => {
      invalidate()
      setDeletingPosition(null)
      toast.success(`${position.symbol} removed`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const stopTracking = useMutation({
    mutationFn: async (instrument: InstrumentPublic) => {
      const { error } = await investmentsDeleteInstrument({
        path: { instrument_id: instrument.id },
      })
      if (error) throw error
      return instrument
    },
    onSuccess: (instrument) => {
      invalidate()
      setDeletingInstrument(null)
      toast.success(`${instrument.symbol} removed`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const removeTrade = useMutation({
    mutationFn: async (trade: TradePublic) => {
      const { error } = await investmentsDeleteTrade({ path: { trade_id: trade.id } })
      if (error) throw error
      return trade
    },
    onSuccess: () => {
      invalidate()
      setDeletingTrade(null)
      toast.success('Trade deleted')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const openTradeFor = (instrumentId: string | null) => {
    setTradingInstrumentId(instrumentId)
    setRecordingTrade(true)
  }

  const currency = portfolio.data?.currency_code ?? 'EUR'
  const hasInstruments = (instruments.data?.count ?? 0) > 0

  return (
    <>
      <PageHeader
        title="Investments"
        description="What you hold, what it cost, and what it is worth today."
      >
        <div className="flex items-center gap-2">
          <Label htmlFor="closed" className="text-muted-foreground text-sm font-normal">
            Show sold
          </Label>
          <Switch id="closed" checked={includeClosed} onCheckedChange={setIncludeClosed} />
        </div>
        <Button variant="outline" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
          <RefreshCw className={refresh.isPending ? 'size-4 animate-spin' : 'size-4'} />
          Refresh prices
        </Button>
        <Button onClick={() => setAddingInstrument(true)}>Add instrument</Button>
      </PageHeader>

      {portfolio.data && portfolio.data.count > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Value today"
            minor={portfolio.data.total_market_value_minor ?? 0}
            currency={currency}
            hint={
              portfolio.data.priced_as_of
                ? `Priced ${formatDateTime(portfolio.data.priced_as_of)}`
                : 'Not priced yet'
            }
          />
          <StatTile
            label="What it cost"
            minor={portfolio.data.total_cost_basis_minor ?? 0}
            currency={currency}
          />
          <StatTile
            label="Unrealised"
            minor={portfolio.data.total_unrealised_gain_minor ?? 0}
            currency={currency}
            signed
            tone="auto"
            hint="On paper, until you sell."
          />
          <StatTile
            label="Realised"
            minor={portfolio.data.total_realised_gain_minor ?? 0}
            currency={currency}
            signed
            tone="auto"
            hint="Locked in by sales, after fees."
          />
        </div>
      ) : null}

      {portfolio.data && (portfolio.data.unpriced_count ?? 0) > 0 ? (
        <Alert>
          <AlertCircle className="size-4" />
          <AlertTitle>The total is partial</AlertTitle>
          <AlertDescription>
            {portfolio.data.unpriced_count === 1
              ? 'One of your holdings has'
              : `${portfolio.data.unpriced_count} of your holdings have`}{' '}
            no price or no exchange rate yet, so{' '}
            {portfolio.data.unpriced_count === 1 ? 'it is' : 'they are'} left out of the value above
            rather than counted as nothing. Refresh prices to fill{' '}
            {portfolio.data.unpriced_count === 1 ? 'it' : 'them'} in.
          </AlertDescription>
        </Alert>
      ) : null}

      <Tabs defaultValue="positions">
        <TabsList>
          <TabsTrigger value="positions">Positions</TabsTrigger>
          <TabsTrigger value="trades">Trades</TabsTrigger>
          <TabsTrigger value="instruments">Tracked</TabsTrigger>
          <TabsTrigger value="rates">Rates</TabsTrigger>
        </TabsList>

        <TabsContent value="positions" className="space-y-4">
          {portfolio.isPending ? (
            <LoadingRows />
          ) : portfolio.isError ? (
            <ErrorState error={portfolio.error} />
          ) : portfolio.data.count === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title={hasInstruments ? 'Nothing held yet' : 'No investments yet'}
              description={
                hasInstruments
                  ? 'You are tracking instruments but have not recorded a trade against any of them.'
                  : 'Track an ETF or a share, then record what you bought. Prices come from the market, the rest from you.'
              }
            >
              {hasInstruments ? (
                <Button onClick={() => openTradeFor(null)}>Record a trade</Button>
              ) : (
                <Button onClick={() => setAddingInstrument(true)}>Add your first instrument</Button>
              )}
            </EmptyState>
          ) : (
            <Card className="overflow-hidden py-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Instrument</TableHead>
                      <TableHead className="text-right">Units</TableHead>
                      <TableHead className="text-right">Price</TableHead>
                      <TableHead className="text-right">Cost</TableHead>
                      <TableHead className="text-right">Value</TableHead>
                      <TableHead className="text-right">Unrealised</TableHead>
                      <TableHead className="text-right">Realised</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {portfolio.data.data.map((position) => (
                      <TableRow
                        key={position.instrument_id}
                        className={position.is_open ? undefined : 'opacity-60'}
                      >
                        <TableCell>
                          <div className="flex items-center gap-2 font-medium">
                            {position.symbol}
                            <Badge variant="secondary">
                              {INSTRUMENT_KIND_LABELS[position.kind] ?? position.kind}
                            </Badge>
                            {position.is_open ? null : <Badge variant="outline">Sold</Badge>}
                          </div>
                          <p className="text-muted-foreground line-clamp-1 text-xs">
                            {position.name}
                          </p>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatQuantity(position.quantity_micro ?? 0, locale)}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-right tabular-nums">
                          {position.last_price_micro === null ||
                          position.last_price_micro === undefined
                            ? '—'
                            : formatPrice(
                                position.last_price_micro,
                                position.currency_code,
                                locale,
                              )}
                          {position.last_price_is_manual ? (
                            <span className="block text-xs">By hand</span>
                          ) : null}
                          {/* The rate is shown next to the price it converts,
                              not only on its own tab. Every other figure in the
                              row has been through it, so this is where someone
                              wondering "converted at what?" is looking. */}
                          {position.fx_rate_micro && position.fx_rate_micro !== MICRO ? (
                            <span className="block text-xs">
                              × {formatRate(position.fx_rate_micro, locale)}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-right">
                          {/* Absent when no exchange rate is known for the
                              listing's currency, in which case there is no
                              honest figure to give. */}
                          {position.cost_basis_minor === null ||
                          position.cost_basis_minor === undefined ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <Money minor={position.cost_basis_minor} currency={currency} />
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {/* A dash, not a zero. "Not known" and "worth
                              nothing" are very different claims to make about
                              someone's money. */}
                          {position.market_value_minor === null ||
                          position.market_value_minor === undefined ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <Money minor={position.market_value_minor} currency={currency} />
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {/* A sold position holds nothing, so there is nothing
                              left to gain or lose on paper. A dash rather than
                              a zero, which would read as "flat" instead of
                              "does not apply". */}
                          {!position.is_open ||
                          position.unrealised_gain_minor === null ||
                          position.unrealised_gain_minor === undefined ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <Money
                              minor={position.unrealised_gain_minor}
                              currency={currency}
                              signed
                              colored
                            />
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {/* Its own column, because it is the only figure a
                              sold position still has, and because an open
                              position can have banked money too: selling half
                              realises a gain while the rest keeps moving. */}
                          {position.realised_gain_minor === null ||
                          position.realised_gain_minor === undefined ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <Money
                              minor={position.realised_gain_minor}
                              currency={currency}
                              signed
                              colored
                            />
                          )}
                        </TableCell>
                        <TableCell>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Manage ${position.symbol}`}
                              >
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem
                                onClick={() => openTradeFor(position.instrument_id)}
                              >
                                <Plus className="size-4" />
                                Record a trade
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() =>
                                  setPricingInstrument(
                                    instruments.data?.data.find(
                                      (one) => one.id === position.instrument_id,
                                    ) ?? null,
                                  )
                                }
                              >
                                <Tag className="size-4" />
                                Set price by hand
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onClick={() =>
                                  setEditingInstrument(
                                    instruments.data?.data.find(
                                      (one) => one.id === position.instrument_id,
                                    ) ?? null,
                                  )
                                }
                              >
                                <Pencil className="size-4" />
                                Edit
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              <DropdownMenuItem
                                variant="destructive"
                                onClick={() => setDeletingPosition(position)}
                              >
                                <Trash2 className="size-4" />
                                Stop tracking
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="trades" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => openTradeFor(null)} disabled={!hasInstruments}>
              Record a trade
            </Button>
          </div>

          {trades.isPending ? (
            <LoadingRows />
          ) : trades.isError ? (
            <ErrorState error={trades.error} />
          ) : trades.data.count === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title="No trades yet"
              description="Every position is built from what you bought and sold, so this is where it starts."
            />
          ) : (
            <Card className="overflow-hidden py-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead>Instrument</TableHead>
                      <TableHead />
                      <TableHead className="text-right">Units</TableHead>
                      <TableHead className="text-right">Price</TableHead>
                      <TableHead className="text-right">Fees</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {trades.data.data.map((trade) => (
                      <TableRow key={trade.id}>
                        <TableCell className="text-muted-foreground">
                          {formatDate(trade.traded_on)}
                        </TableCell>
                        <TableCell className="font-medium">{trade.symbol}</TableCell>
                        <TableCell>
                          <Badge variant={trade.side === 'buy' ? 'secondary' : 'outline'}>
                            {TRADE_SIDE_LABELS[trade.side] ?? trade.side}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatQuantity(trade.quantity_micro, locale)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {formatPrice(trade.price_micro, trade.currency_code, locale)}
                        </TableCell>
                        <TableCell className="text-right">
                          <Money
                            minor={trade.fee_minor ?? 0}
                            currency={trade.currency_code ?? currency}
                          />
                        </TableCell>
                        <TableCell>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Manage the ${trade.symbol} trade`}
                              >
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem
                                variant="destructive"
                                onClick={() => setDeletingTrade(trade)}
                              >
                                <Trash2 className="size-4" />
                                Delete
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}
        </TabsContent>

        {/* Every instrument being tracked, held or not. The positions tab
            deliberately hides one that has never been traded, because it is
            not a holding; without this tab such a row would exist in the
            database and appear on no screen, which makes it impossible to
            correct a typo or drop something no longer wanted. */}
        <TabsContent value="instruments" className="space-y-4">
          <div className="flex justify-end">
            <Button onClick={() => setAddingInstrument(true)}>Track an instrument</Button>
          </div>

          {instruments.isPending ? (
            <LoadingRows />
          ) : instruments.isError ? (
            <ErrorState error={instruments.error} />
          ) : instruments.data.count === 0 ? (
            <EmptyState
              icon={TrendingUp}
              title="Nothing tracked yet"
              description="Track an ETF or a share to price it and record trades against it."
            >
              <Button onClick={() => setAddingInstrument(true)}>Add your first instrument</Button>
            </EmptyState>
          ) : (
            <Card className="overflow-hidden py-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Instrument</TableHead>
                      <TableHead>Exchange</TableHead>
                      <TableHead className="text-right">Last price</TableHead>
                      <TableHead>Priced</TableHead>
                      <TableHead className="text-right">Trades</TableHead>
                      <TableHead className="w-10" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {instruments.data.data.map((instrument) => (
                      <TableRow key={instrument.id}>
                        <TableCell>
                          <div className="flex items-center gap-2 font-medium">
                            {instrument.symbol}
                            <Badge variant="secondary">
                              {INSTRUMENT_KIND_LABELS[instrument.kind ?? InstrumentKind.OTHER] ??
                                instrument.kind}
                            </Badge>
                          </div>
                          <p className="text-muted-foreground line-clamp-1 text-xs">
                            {instrument.name}
                          </p>
                        </TableCell>
                        <TableCell className="text-muted-foreground text-sm">
                          {instrument.exchange ?? '—'}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {instrument.last_price_micro === null ||
                          instrument.last_price_micro === undefined ? (
                            <span className="text-muted-foreground">—</span>
                          ) : (
                            <>
                              {formatPrice(
                                instrument.last_price_micro,
                                instrument.currency_code,
                                locale,
                              )}{' '}
                              <span className="text-muted-foreground text-xs">
                                {instrument.currency_code}
                              </span>
                            </>
                          )}
                        </TableCell>
                        <TableCell className="text-muted-foreground text-xs">
                          {/* When the provider was last asked, not what moment
                              the price refers to. It is the one that says
                              whether pressing refresh will cost an API call. */}
                          {instrument.last_priced_at
                            ? formatDateTime(instrument.last_priced_at)
                            : 'Never'}
                          {/* Said plainly. A number someone typed and a number
                              a market reported are both useful and are not the
                              same claim. */}
                          {instrument.last_price_is_manual ? (
                            <span className="block">By hand</span>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {instrument.trade_count ?? 0}
                        </TableCell>
                        <TableCell>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                aria-label={`Manage ${instrument.symbol}`}
                              >
                                <MoreHorizontal className="size-4" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                              <DropdownMenuItem onClick={() => openTradeFor(instrument.id)}>
                                <Plus className="size-4" />
                                Record a trade
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => setPricingInstrument(instrument)}>
                                <Tag className="size-4" />
                                Set price by hand
                              </DropdownMenuItem>
                              <DropdownMenuItem onClick={() => setEditingInstrument(instrument)}>
                                <Pencil className="size-4" />
                                Edit
                              </DropdownMenuItem>
                              <DropdownMenuSeparator />
                              {/* Offered only when it would work. Deleting an
                                  instrument that still has trades is refused,
                                  and a button that always fails teaches nothing
                                  except not to trust the buttons. */}
                              <DropdownMenuItem
                                variant="destructive"
                                disabled={(instrument.trade_count ?? 0) > 0}
                                onClick={() => setDeletingInstrument(instrument)}
                              >
                                <Trash2 className="size-4" />
                                {(instrument.trade_count ?? 0) > 0
                                  ? 'Delete its trades first'
                                  : 'Stop tracking'}
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          )}
        </TabsContent>
        {/* The conversion behind every total on this page. A figure restated
            into the household's currency is only as checkable as the rate
            behind it, and one rate per pair restates a whole position's
            history rather than each trade at its own date. Both facts are
            better shown than buried. */}
        <TabsContent value="rates" className="space-y-4">
          {fxRates.isPending || !fxRates.data ? (
            <LoadingRows />
          ) : fxRates.isError ? (
            <ErrorState error={fxRates.error} />
          ) : (
            <>
              {fxRates.data.missing && fxRates.data.missing.length > 0 ? (
                <Alert variant="destructive">
                  <AlertCircle />
                  <AlertTitle>No rate for {fxRates.data.missing.join(', ')}</AlertTitle>
                  <AlertDescription>
                    Holdings in {fxRates.data.missing.length === 1 ? 'that currency' : 'those'}{' '}
                    cannot be valued until a rate is fetched. Refresh prices to get one.
                  </AlertDescription>
                </Alert>
              ) : null}

              {fxRates.data.count === 0 ? (
                <EmptyState
                  icon={TrendingUp}
                  title="No conversion needed"
                  description={`Everything you hold already quotes in ${fxRates.data.quote_code}, so nothing is converted.`}
                />
              ) : (
                <Card className="overflow-hidden py-0">
                  <div className="overflow-x-auto">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Pair</TableHead>
                          <TableHead className="text-right">Rate</TableHead>
                          <TableHead>Rate date</TableHead>
                          <TableHead>Fetched</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {fxRates.data.data.map((rate) => (
                          <TableRow
                            key={`${rate.base_code}-${rate.quote_code}`}
                            className={rate.in_use ? undefined : 'opacity-60'}
                          >
                            <TableCell>
                              <div className="flex items-center gap-2 font-medium">
                                {rate.base_code} → {rate.quote_code}
                                {rate.in_use ? null : <Badge variant="outline">Not held</Badge>}
                              </div>
                              <p className="text-muted-foreground text-xs">
                                1 {rate.base_code} buys {formatRate(rate.rate_micro, locale)}{' '}
                                {rate.quote_code}
                              </p>
                            </TableCell>
                            <TableCell className="text-right tabular-nums">
                              {formatRate(rate.rate_micro, locale)}
                            </TableCell>
                            {/* The day the rate refers to, and the day this app
                                asked for it. Over a weekend they differ, and a
                                single date would hide which kind of stale it is. */}
                            <TableCell className="text-muted-foreground text-xs">
                              {formatDate(rate.as_of)}
                            </TableCell>
                            <TableCell className="text-muted-foreground text-xs">
                              {rate.fetched_at ? formatDateTime(rate.fetched_at) : '—'}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </Card>
              )}

              <p className="text-muted-foreground text-xs">
                Rates come from Frankfurter, which publishes the European Central Bank's daily
                reference rates. One rate is kept per pair, so a cost basis paid years ago is
                restated at today's rate: a gain shown in {fxRates.data.quote_code} mixes the
                market's movement with the currency's.
              </p>
            </>
          )}
        </TabsContent>
      </Tabs>

      <InstrumentDialog
        open={addingInstrument || editingInstrument !== null}
        instrument={editingInstrument}
        onOpenChange={(open) => {
          if (!open) {
            setAddingInstrument(false)
            setEditingInstrument(null)
          }
        }}
      />

      <TradeDialog
        open={recordingTrade}
        instrumentId={tradingInstrumentId}
        onOpenChange={(open) => {
          if (!open) {
            setRecordingTrade(false)
            setTradingInstrumentId(null)
          }
        }}
      />

      <PriceDialog
        open={pricingInstrument !== null}
        instrument={pricingInstrument}
        onOpenChange={(open) => !open && setPricingInstrument(null)}
      />

      <ConfirmDialog
        open={deletingPosition !== null}
        onOpenChange={(open) => !open && setDeletingPosition(null)}
        title={`Stop tracking ${deletingPosition?.symbol}?`}
        description="This only works once its trades are gone. The history is what the position is made of."
        confirmLabel="Stop tracking"
        pending={removeInstrument.isPending}
        onConfirm={() => deletingPosition && removeInstrument.mutate(deletingPosition)}
      />

      <ConfirmDialog
        open={deletingInstrument !== null}
        onOpenChange={(open) => !open && setDeletingInstrument(null)}
        title={`Stop tracking ${deletingInstrument?.symbol}?`}
        description="It has no trades against it, so nothing recorded is lost. You can track it again later."
        confirmLabel="Stop tracking"
        pending={stopTracking.isPending}
        onConfirm={() => deletingInstrument && stopTracking.mutate(deletingInstrument)}
      />

      <ConfirmDialog
        open={deletingTrade !== null}
        onOpenChange={(open) => !open && setDeletingTrade(null)}
        title="Delete this trade?"
        description="The position is rebuilt from what is left, so its units, cost and gain will all change."
        confirmLabel="Delete trade"
        pending={removeTrade.isPending}
        onConfirm={() => deletingTrade && removeTrade.mutate(deletingTrade)}
      />
    </>
  )
}
