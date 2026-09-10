import datetime
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel import Session

from app.exceptions import (
    AccountNotFoundError,
    HouseholdNotFoundError,
    InstrumentExistsError,
    InstrumentInUseError,
    InstrumentNotFoundError,
    InstrumentNotPriceableError,
    InsufficientUnitsError,
    NotABrokerageAccountError,
    PriceProviderError,
    PriceProviderNotConfiguredError,
    TradeNotConvertibleError,
    TradeNotFoundError,
)
from app.models import (
    Account,
    AccountType,
    FxRatePublic,
    FxRatesPublic,
    HouseholdContext,
    Instrument,
    InstrumentCreate,
    InstrumentPriceUpdate,
    InstrumentPublic,
    InstrumentsPublic,
    InstrumentUpdate,
    Message,
    PortfolioPublic,
    PositionPublic,
    PriceRefreshResult,
    QuoteFailure,
    SymbolMatch,
    SymbolMatchesPublic,
    Trade,
    TradeCreate,
    TradePublic,
    TradeSide,
    TradesPublic,
    TradeUpdate,
)
from app.models.fields import MICRO, apportion_minor, convert_minor, market_value_minor
from app.repositories.account import AccountRepository
from app.repositories.household import HouseholdRepository
from app.repositories.investment import FxRateRepository, InstrumentRepository, TradeRepository
from app.services.prices import PriceProvider, Quote

# The most instruments one household can hold, and so the most a refresh will
# ask the provider about. It is a bound on an outbound request rather than on
# the data: without one, a household with a thousand rows would aim a thousand
# requests at a provider that rate limits, and be blocked for the trouble. No
# household portfolio comes near it.
MAX_INSTRUMENTS = 500


def _recorded_order(trade: Trade) -> tuple[datetime.date, datetime.datetime]:
    """Sort key putting a day's trades in the order they were recorded.

    Two timestamps are only ever compared when two trades share a date, which
    is exactly what a second trade in the same instrument on the same day
    does. Both carry a zone, since the column is ``timestamptz`` and everything
    the app builds is tz-aware, so they compare as the moments they are.

    A trade with no timestamp at all sorts last on its day: not having been
    written yet makes it the most recent thing to have happened on it. The
    stand-in has to carry a zone too, or that comparison is the one that
    raises.

    Args:
        trade: The trade to place.

    Returns:
        The date it happened, and when it was recorded.
    """
    created_at = trade.created_at

    if created_at is None:
        return trade.traded_on, datetime.datetime.max.replace(tzinfo=datetime.UTC)

    return trade.traded_on, created_at


@dataclass(frozen=True)
class Position:
    """What folding an instrument's trades leaves behind.

    Every figure is in the instrument's own currency, because that is the
    currency the trades were in. Converting is a later step, and a separate
    one: mixing the two here is how a cost basis ends up restated twice.
    """

    quantity_micro: int
    cost_basis_minor: int
    realised_gain_minor: int


class InvestmentService:
    """Provide services for tracking instruments, trades and portfolio value."""

    def __init__(
        self,
        session: Session,
        instrument_repository: InstrumentRepository,
        trade_repository: TradeRepository,
        fx_rate_repository: FxRateRepository,
        household_repository: HouseholdRepository,
        price_provider: PriceProvider,
        account_repository: AccountRepository,
        price_cache_hours: float = 2.0,
    ) -> None:
        """Initialize the investment service.

        Args:
            session: The database session.
            instrument_repository: The instrument repository instance.
            trade_repository: The trade repository instance.
            fx_rate_repository: The FX rate repository instance.
            household_repository: The household repository instance, used to
                read the currency the portfolio is reported in.
            price_provider: Where market prices come from.
            account_repository: The account repository instance, used to check
                that a trade settles through a brokerage account.
            price_cache_hours: How long a fetched price or rate is reused
                before the provider is asked about it again.
        """
        self.session = session
        self.instrument_repository = instrument_repository
        self.trade_repository = trade_repository
        self.fx_rate_repository = fx_rate_repository
        self.household_repository = household_repository
        self.price_provider = price_provider
        self.account_repository = account_repository
        self.price_cache_hours = max(0.0, price_cache_hours)

    # --- instruments -------------------------------------------------------

    def create_instrument(self, household: HouseholdContext, instrument_create: InstrumentCreate) -> InstrumentPublic:
        """Start tracking an instrument, settling what currency it quotes in.

        The currency is a property of the listing rather than of the household,
        so it has to come from somewhere. A caller that supplies one has said
        where, and nothing is asked of the provider at all: the row is created
        offline. That is the path worth protecting, because adding a line to a
        list should not depend on a website being up, and because the symbol
        search the caller just used already reported the currency.

        Without one, the provider is asked. Its search is the endpoint that
        answers, since the quote endpoint of a keyed provider reports a price
        and no currency. A provider whose search omits it is asked for a quote
        instead, which is the older path and still the right one for it.

        Args:
            household: The household context.
            instrument_create: The instrument to track.

        Returns:
            The instrument. It carries no price until the first refresh.

        Raises:
            InstrumentExistsError: If the household already tracks that symbol.
            InstrumentNotPriceableError: If the provider does not know the
                symbol and no currency was supplied to track it by hand.
            PriceProviderError: If the provider is unreachable and no currency
                was supplied.
            PriceProviderNotConfiguredError: If market data is switched off and
                no currency was supplied.
        """
        symbol = self._normalize_symbol(instrument_create.symbol)
        self._require_symbol_is_free(household=household, symbol=symbol)

        match: SymbolMatch | None = None
        quote = None

        if instrument_create.currency_code is None:
            if not self.price_provider.is_configured:
                raise PriceProviderNotConfiguredError from None

            match = self._find_listing(symbol)
            if match is None or match.currency_code is None:
                found, _ = self.price_provider.quotes([symbol])
                quote = found.get(symbol)

        currency_code = (
            instrument_create.currency_code
            or (match.currency_code if match else None)
            or (quote.currency_code if quote else None)
        )
        if currency_code is None:
            raise InstrumentNotPriceableError(symbol=symbol) from None

        instrument = Instrument.model_validate(
            instrument_create,
            update={
                "household_id": household.household_id,
                "symbol": symbol,
                "currency_code": currency_code.upper(),
                "exchange": (
                    instrument_create.exchange
                    or (match.exchange if match else None)
                    or (quote.exchange if quote else None)
                ),
                "last_price_micro": quote.price_micro if quote else None,
                "last_price_at": quote.as_of if quote else None,
                "last_priced_at": (datetime.datetime.now(datetime.UTC) if quote else None),
            },
        )
        self.instrument_repository.save(instrument)
        self.session.commit()

        return InstrumentPublic.model_validate(instrument)

    def _find_listing(self, symbol: str) -> SymbolMatch | None:
        """Look the symbol up in the provider's search index.

        Args:
            symbol: The normalized ticker symbol.

        Returns:
            The match whose symbol is exactly this one, or None when the
            provider offers no such listing or cannot be reached. Being unable
            to look it up is not fatal here: the caller has a second way to
            settle the currency and a third way to report that it could not.
        """
        try:
            matches = self.price_provider.search(query=symbol, limit=10)
        except (PriceProviderError, PriceProviderNotConfiguredError):
            return None

        return next((match for match in matches if match.symbol.upper() == symbol), None)

    def list_instruments(self, household: HouseholdContext, skip: int = 0, limit: int = 100) -> InstrumentsPublic:
        """List the instruments the household tracks.

        Args:
            household: The household context.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            The instruments on the page, and how many there are in total.
        """
        instruments, count = self.instrument_repository.list_for_household(
            household_id=household.household_id, skip=skip, limit=limit
        )
        trade_counts = self.trade_repository.counts_by_instrument(household_id=household.household_id)

        return InstrumentsPublic(
            data=[
                InstrumentPublic.model_validate(instrument, update={"trade_count": trade_counts.get(instrument.id, 0)})
                for instrument in instruments
            ],
            count=count,
        )

    def get_instrument(self, household: HouseholdContext, instrument_id: uuid.UUID) -> InstrumentPublic:
        """Get one instrument of the household.

        Args:
            household: The household context.
            instrument_id: The ID of the instrument.

        Returns:
            The instrument.

        Raises:
            InstrumentNotFoundError: If it does not exist in the household.
        """
        return InstrumentPublic.model_validate(self.require_instrument(household, instrument_id))

    def update_instrument(
        self, household: HouseholdContext, instrument_id: uuid.UUID, instrument_update: InstrumentUpdate
    ) -> InstrumentPublic:
        """Rename or re-label an instrument.

        Neither the symbol nor the currency can be changed. Both describe the
        listing every stored price and every recorded trade was measured
        against, so changing either would silently restate history.

        Args:
            household: The household context.
            instrument_id: The ID of the instrument to update.
            instrument_update: The fields to update.

        Returns:
            The updated instrument.

        Raises:
            InstrumentNotFoundError: If it does not exist in the household.
        """
        instrument = self.require_instrument(household, instrument_id)
        instrument.sqlmodel_update(instrument_update.model_dump(exclude_unset=True))

        self.instrument_repository.save(instrument)
        self.session.commit()

        return InstrumentPublic.model_validate(instrument)

    def set_instrument_price(
        self,
        household: HouseholdContext,
        instrument_id: uuid.UUID,
        price_update: InstrumentPriceUpdate,
    ) -> InstrumentPublic:
        """Record a price typed in by hand.

        This exists because the provider is the one part of the app that can
        refuse. A free plan allows twenty calls a day and charges one per
        holding, so a portfolio can run out of them; a provider can also not
        carry a listing at all, or be switched off. None of that should leave
        someone unable to say what their holding is worth when they are looking
        straight at the number on their broker's screen.

        The price is stored the same way a fetched one is, so every total,
        conversion and gain treats it identically. What differs is that the row
        remembers it was typed, and that is reported rather than smoothed over:
        a figure someone entered and a figure a market reported are both useful
        and are not the same claim.

        It also counts as a fresh price for the cache, which is deliberate. The
        app has a current price and no reason to spend a call replacing it.

        Args:
            household: The household context.
            instrument_id: The ID of the instrument to price.
            price_update: The price, in the instrument's own currency.

        Returns:
            The instrument, carrying the new price.

        Raises:
            InstrumentNotFoundError: If it does not exist in the household.
        """
        instrument = self.require_instrument(household, instrument_id)
        now = datetime.datetime.now(datetime.UTC)

        instrument.last_price_micro = price_update.price_micro
        instrument.last_price_at = price_update.as_of or now
        instrument.last_priced_at = now
        instrument.last_price_is_manual = True

        self.instrument_repository.save(instrument)
        self.session.commit()

        return InstrumentPublic.model_validate(
            instrument,
            update={
                "trade_count": self.trade_repository.count_for_instrument(
                    instrument_id=instrument.id, household_id=household.household_id
                )
            },
        )

    def delete_instrument(self, household: HouseholdContext, instrument_id: uuid.UUID) -> Message:
        """Stop tracking an instrument that has no trades.

        Args:
            household: The household context.
            instrument_id: The ID of the instrument to delete.

        Returns:
            A confirmation message.

        Raises:
            InstrumentNotFoundError: If it does not exist in the household.
            InstrumentInUseError: If it still has trades.
        """
        instrument = self.require_instrument(household, instrument_id)

        if self.trade_repository.count_for_instrument(instrument_id=instrument.id, household_id=household.household_id):
            raise InstrumentInUseError(symbol=instrument.symbol) from None

        self.instrument_repository.delete(instrument)
        self.session.commit()

        return Message(message="Instrument deleted.")

    def require_instrument(self, household: HouseholdContext, instrument_id: uuid.UUID) -> Instrument:
        """Load an instrument of the household.

        Args:
            household: The household context.
            instrument_id: The ID of the instrument.

        Returns:
            The instrument.

        Raises:
            InstrumentNotFoundError: If it does not exist in the household.
        """
        instrument = self.instrument_repository.get_for_household(
            entity_id=instrument_id, household_id=household.household_id
        )

        if not instrument:
            raise InstrumentNotFoundError from None

        return instrument

    # --- trades ------------------------------------------------------------

    def create_trade(
        self, household: HouseholdContext, trade_create: TradeCreate, created_by_user_id: uuid.UUID | None = None
    ) -> TradePublic:
        """Record a buy or a sell.

        Args:
            household: The household context.
            trade_create: The trade to record.
            created_by_user_id: The user recording it, for the audit trail.

        Returns:
            The recorded trade.

        Raises:
            InstrumentNotFoundError: If the instrument does not exist in the household.
            InsufficientUnitsError: If the trade would leave the position short.
            AccountNotFoundError: If the cash account does not exist in the household.
            TradeNotConvertibleError: If the cash side is wanted, the listing
                quotes in another currency, and no rate is known to convert it.
        """
        instrument = self.require_instrument(household, trade_create.instrument_id)

        trade = Trade.model_validate(
            trade_create,
            update={"household_id": household.household_id, "created_by_user_id": created_by_user_id},
        )
        self._require_position_stays_solvent(instrument=instrument, added=trade)

        if trade.brokerage_account_id is not None:
            trade.cash_amount_minor = self._cash_amount(
                household=household, instrument=instrument, trade=trade, supplied=trade_create.cash_amount_minor
            )

        self._require_brokerage(household, trade.brokerage_account_id)
        self.trade_repository.save(trade)
        self.session.commit()

        return self._trade_to_public(trade=trade, instrument=instrument)

    def list_trades(
        self,
        household: HouseholdContext,
        instrument_id: uuid.UUID | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> TradesPublic:
        """List the household's trades, newest first.

        Args:
            household: The household context.
            instrument_id: An optional instrument to filter on.
            skip: Number of records to skip.
            limit: Maximum number of records to return.

        Returns:
            The trades on the page, and how many there are in total.
        """
        if instrument_id is not None:
            # Resolved through the household scope before it reaches the query,
            # so an instrument of another household is a 404 rather than an
            # empty page that hints the ID exists.
            self.require_instrument(household, instrument_id)

        trades, count = self.trade_repository.list_for_household(
            household_id=household.household_id, instrument_id=instrument_id, skip=skip, limit=limit
        )
        instruments = self._instruments_by_id(household)

        return TradesPublic(
            data=[
                self._trade_to_public(trade=trade, instrument=instruments.get(trade.instrument_id)) for trade in trades
            ],
            count=count,
        )

    def get_trade(self, household: HouseholdContext, trade_id: uuid.UUID) -> TradePublic:
        """Get one trade of the household.

        Args:
            household: The household context.
            trade_id: The ID of the trade.

        Returns:
            The trade.

        Raises:
            TradeNotFoundError: If it does not exist in the household.
        """
        trade = self._require_trade(household, trade_id)
        instrument = self.instrument_repository.get_for_household(
            entity_id=trade.instrument_id, household_id=household.household_id
        )

        return self._trade_to_public(trade=trade, instrument=instrument)

    def update_trade(self, household: HouseholdContext, trade_id: uuid.UUID, trade_update: TradeUpdate) -> TradePublic:
        """Correct a recorded trade.

        Args:
            household: The household context.
            trade_id: The ID of the trade to correct.
            trade_update: The fields to change.

        Returns:
            The corrected trade.

        Raises:
            TradeNotFoundError: If it does not exist in the household.
            InstrumentNotFoundError: If its instrument has gone.
            InsufficientUnitsError: If the correction would leave the position short.
        """
        trade = self._require_trade(household, trade_id)
        instrument = self.require_instrument(household, trade.instrument_id)
        changes = trade_update.model_dump(exclude_unset=True)

        trade.sqlmodel_update(changes)
        self._require_position_stays_solvent(instrument=instrument)

        if trade.brokerage_account_id is None:
            # The cash side was removed, or was never there. Either way nothing
            # should be left moving money on its behalf.
            trade.cash_amount_minor = None
        else:
            # Recomputed unless the caller said what it should be. A corrected
            # quantity or price changes what the trade cost, and a stale cash
            # amount would leave the ledger disagreeing with the trade it came
            # from.
            trade.cash_amount_minor = self._cash_amount(
                household=household,
                instrument=instrument,
                trade=trade,
                supplied=changes.get("cash_amount_minor"),
            )

        self._require_brokerage(household, trade.brokerage_account_id)
        self.trade_repository.save(trade)
        self.session.commit()

        return self._trade_to_public(trade=trade, instrument=instrument)

    def delete_trade(self, household: HouseholdContext, trade_id: uuid.UUID) -> Message:
        """Remove a trade that should not have been recorded.

        Args:
            household: The household context.
            trade_id: The ID of the trade to remove.

        Returns:
            A confirmation message.

        Raises:
            TradeNotFoundError: If it does not exist in the household.
            InstrumentNotFoundError: If its instrument has gone.
            InsufficientUnitsError: If removing it would leave the position short,
                which is what happens when a later sale depended on the units
                this trade brought in.
        """
        trade = self._require_trade(household, trade_id)
        instrument = self.require_instrument(household, trade.instrument_id)

        # Nothing to unwind: the brokerage balance is folded from the trades
        # themselves, so removing the trade removes its effect on the balance.
        self.trade_repository.delete(trade)
        self.trade_repository.flush()
        self._require_position_stays_solvent(instrument=instrument)

        self.session.commit()

        return Message(message="Trade deleted.")

    # --- portfolio ---------------------------------------------------------

    def get_portfolio(self, household: HouseholdContext, include_closed: bool = False) -> PortfolioPublic:
        """Value everything the household holds, in the household's currency.

        Args:
            household: The household context.
            include_closed: Whether to include positions sold down to nothing.
                They are worth nothing, but the gain they realised is real.

        Returns:
            The positions and the totals over them.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        base_currency = self._household_currency(household)
        instruments, _ = self.instrument_repository.list_for_household(
            household_id=household.household_id, limit=MAX_INSTRUMENTS
        )
        trades = self._trades_by_instrument(household)
        rates = self.fx_rate_repository.rates_into(
            quote_code=base_currency,
            base_codes=[currency for currency in {i.currency_code for i in instruments} if currency != base_currency],
        )

        positions: list[PositionPublic] = []
        for instrument in instruments:
            folded = self._fold(trades.get(instrument.id, []))
            is_open = folded.quantity_micro > 0

            rate = rates.get(instrument.currency_code)
            # A holding already in the household's currency needs no rate and
            # must never wait on one, so it gets the identity rather than a
            # lookup that could come back empty.
            rate_micro = MICRO if instrument.currency_code == base_currency else (rate.rate_micro if rate else None)

            positions.append(
                self._to_position(instrument=instrument, folded=folded, rate_micro=rate_micro, is_open=is_open)
            )

        # Both worked out before anything is hidden, and for the same reason. A
        # realised gain is a fact about the past: the money was banked, and it
        # does not stop having been banked because the position that produced it
        # is closed and filtered out of the list. The count of what could not be
        # valued has to follow it, or a position sold in full in a currency with
        # no stored rate would add nothing to the total and warn about nothing
        # either, which is the one case where the total is silently short.
        realised_gain_minor = sum(position.realised_gain_minor or 0 for position in positions)
        unpriced_count = sum(
            1
            for position in positions
            if position.cost_basis_minor is None or (position.is_open and position.market_value_minor is None)
        )

        if not include_closed:
            positions = [position for position in positions if position.is_open]

        return self._to_portfolio(
            currency_code=base_currency,
            positions=positions,
            realised_gain_minor=realised_gain_minor,
            unpriced_count=unpriced_count,
        )

    def refresh_prices(self, household: HouseholdContext) -> PriceRefreshResult:
        """Fetch a fresh price for every instrument, and the rates to value them.

        Args:
            household: The household context.

        Returns:
            What was updated, and what could not be.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
            PriceProviderNotConfiguredError: If market data is switched off.
            PriceProviderError: If the price provider cannot be reached at all.
                An unreachable *rate* provider is reported as a failed pair
                rather than raised, because the prices already fetched are good
                and must not be thrown away with it.
        """
        if not self.price_provider.is_configured:
            raise PriceProviderNotConfiguredError from None

        base_currency = self._household_currency(household)
        instruments, _ = self.instrument_repository.list_for_household(
            household_id=household.household_id, limit=MAX_INSTRUMENTS
        )
        refreshed_at = datetime.datetime.now(datetime.UTC)

        if not instruments:
            return PriceRefreshResult(updated_count=0, cached_count=0, failures=[], refreshed_at=refreshed_at)

        # The cache is the stored price itself. Anything fetched inside the
        # window is left alone, so a second refresh a minute after the first
        # costs nothing. That matters more than it looks: the provider charges
        # one API call per symbol, not per request, and a free plan allows
        # twenty a day. Without this, opening the page twice could spend a
        # quarter of a day's budget on prices that had not moved.
        cutoff = refreshed_at - datetime.timedelta(hours=self.price_cache_hours)
        stale = [
            instrument
            for instrument in instruments
            if instrument.last_priced_at is None or instrument.last_priced_at < cutoff
        ]
        cached_count = len(instruments) - len(stale)

        quotes: dict[str, Quote] = {}
        failures: dict[str, str] = {}

        if stale:
            quotes, failures = self.price_provider.quotes(
                [instrument.symbol for instrument in stale],
                # Some providers never say what a listing quotes in. The stored
                # currency is then the only way to read their price correctly,
                # so it is handed over rather than guessed at.
                currencies={instrument.symbol: instrument.currency_code for instrument in stale},
            )

        for instrument in stale:
            quote = quotes.get(instrument.symbol)
            if quote is None:
                continue

            instrument.last_price_micro = quote.price_micro
            instrument.last_price_at = quote.as_of
            # A fetched price supersedes a typed one, flag included. The flag
            # describes the price on the row, so it has to move with it.
            instrument.last_price_is_manual = False
            # Set only on success, and deliberately. Recording the attempt
            # instead would put a symbol that failed behind the cache window
            # too, so a retry would do nothing for two hours. A refresh is a
            # button someone presses, so retrying costs only what they choose
            # to spend.
            instrument.last_priced_at = refreshed_at
            # The provider is the authority on what a listing quotes in, and a
            # listing can be re-denominated. Following it keeps the stored
            # price and the stored currency describing the same thing.
            if quote.currency_code:
                instrument.currency_code = quote.currency_code
            if quote.exchange and not instrument.exchange:
                instrument.exchange = quote.exchange

            self.instrument_repository.add(instrument)

        # Rates come from a different provider, so its being unreachable says
        # nothing about the quotes already fetched. Letting it raise here would
        # throw those away unstored, spend the API calls again on the next
        # press, and report a failure for work that mostly succeeded. Reported
        # as a failed pair instead, exactly as a symbol the quote provider could
        # not answer for is.
        try:
            failures.update(self._refresh_fx_rates(instruments=instruments, base_currency=base_currency, cutoff=cutoff))
        except (PriceProviderError, PriceProviderNotConfiguredError) as exc:
            failures["Exchange rates"] = exc.message

        self.session.commit()

        return PriceRefreshResult(
            updated_count=len(quotes),
            cached_count=cached_count,
            failures=[QuoteFailure(symbol=symbol, reason=reason) for symbol, reason in sorted(failures.items())],
            refreshed_at=refreshed_at,
        )

    def list_fx_rates(self, household: HouseholdContext) -> FxRatesPublic:
        """Show the exchange rates behind the household's converted figures.

        Every money figure on the portfolio is restated into the household's
        currency, and a restated figure is only as trustworthy as the rate
        behind it. This makes that rate visible: which pair, what it is, what
        day it refers to, and when it was last fetched.

        Rates are stored per pair rather than per trade date, so one rate
        restates a whole position's history. That is the caveat worth being
        able to see, rather than one buried in a docstring.

        Args:
            household: The household context.

        Returns:
            The rates converting into the household's currency, and the names
            of any currency held that has no rate at all.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        base_currency = self._household_currency(household)
        instruments, _ = self.instrument_repository.list_for_household(
            household_id=household.household_id, limit=MAX_INSTRUMENTS
        )
        held = {instrument.currency_code for instrument in instruments} - {base_currency}
        stored = self.fx_rate_repository.list_into(quote_code=base_currency)

        # A rate for a currency nothing is held in any more is still shown, but
        # marked. Hiding it would make a figure converted before the last sale
        # look like it came from nowhere.
        rates = [
            FxRatePublic(
                base_code=rate.base_code,
                quote_code=rate.quote_code,
                rate_micro=rate.rate_micro,
                as_of=rate.as_of,
                fetched_at=rate.updated_at or rate.created_at,
                in_use=rate.base_code in held,
            )
            for rate in stored
        ]

        return FxRatesPublic(
            quote_code=base_currency,
            data=rates,
            count=len(rates),
            missing=sorted(held - {rate.base_code for rate in stored}),
        )

    def search_symbols(self, query: str, limit: int = 10) -> SymbolMatchesPublic:
        """Look up listings by name or partial ticker.

        Args:
            query: What the user typed.
            limit: The most matches to return.

        Returns:
            The matching listings.

        Raises:
            PriceProviderNotConfiguredError: If market data is switched off.
            PriceProviderError: If the provider cannot be reached.
        """
        matches = self.price_provider.search(query=query, limit=limit)

        return SymbolMatchesPublic(data=matches, count=len(matches))

    # --- internals ---------------------------------------------------------

    # --- the cash side -----------------------------------------------------
    #
    # A trade is recorded twice over: once as units of a holding, and once as
    # cash leaving or reaching a brokerage account. The second half is optional,
    # since a trade is a fact about a holding whether or not the cash is tracked
    # here, and every trade recorded before this existed has none.
    #
    # Nothing is written to the ledger for it. A brokerage balance is folded
    # from its trades alongside its transactions, so the amount stored on the
    # trade is the whole record: buying takes it out of the broker and selling
    # puts it back. Getting money to the broker in the first place is an
    # ordinary transfer from a bank account, recorded like any other, which is
    # what lets that balance hold cash between trades.

    def _cash_amount(
        self,
        household: HouseholdContext,
        instrument: Instrument,
        trade: Trade,
        supplied: int | None,
    ) -> int:
        """Work out what actually moved, in the household's currency.

        A supplied figure always wins. It is the one the bank charged, and no
        conversion this app can do will match it: a broker's rate on the day is
        never a central bank's reference rate.

        Args:
            household: The household context.
            instrument: The instrument traded.
            trade: The trade, already carrying its final quantity and price.
            supplied: What the caller said moved, if anything.

        Returns:
            The amount, in minor units of the household's currency.

        Raises:
            TradeNotConvertibleError: If nothing was supplied, the listing
                quotes in another currency, and no rate is known.
        """
        if supplied is not None:
            return supplied

        gross_minor = market_value_minor(trade.quantity_micro, trade.price_micro)
        # A fee adds to what a purchase costs and comes off what a sale returns,
        # which is the same rule the position fold uses. A sale whose fee
        # exceeds its proceeds returns nothing rather than a negative amount:
        # money cannot move backwards through one leg of a transfer.
        native_minor = (
            gross_minor + trade.fee_minor if trade.side == TradeSide.BUY else max(0, gross_minor - trade.fee_minor)
        )

        base_currency = self._household_currency(household)
        if instrument.currency_code == base_currency:
            return native_minor

        rate = self.fx_rate_repository.rates_into(quote_code=base_currency, base_codes=[instrument.currency_code]).get(
            instrument.currency_code
        )

        if rate is None:
            raise TradeNotConvertibleError(
                currency_code=instrument.currency_code, base_currency=base_currency
            ) from None

        return convert_minor(native_minor, rate.rate_micro)

    def _require_brokerage(self, household: HouseholdContext, account_id: uuid.UUID | None) -> None:
        """Check that a trade settles through a brokerage account of this household.

        The type matters because the balance of a brokerage account is folded
        from its trades as well as its transactions. A trade pointed at a
        savings account would quietly take money out of real savings that no
        transaction explains.

        Args:
            household: The household context.
            account_id: The account the trade settles through, if any.

        Raises:
            AccountNotFoundError: If it is missing or belongs to another household.
            NotABrokerageAccountError: If it is not a brokerage account.
        """
        if account_id is None:
            return

        account = self._require_account(household, account_id)

        if account.type != AccountType.BROKERAGE:
            raise NotABrokerageAccountError(name=account.name) from None

    def _require_account(self, household: HouseholdContext, account_id: uuid.UUID | None) -> Account:
        """Load one of the household's accounts, refusing anything else.

        Args:
            household: The household context.
            account_id: The ID of the account.

        Returns:
            The account.

        Raises:
            AccountNotFoundError: If it is missing, or belongs to another
                household. The two are one answer on purpose: telling someone
                an account exists but is not theirs is telling them something
                about another household.
        """
        account = (
            None
            if account_id is None
            else self.account_repository.get_for_household(entity_id=account_id, household_id=household.household_id)
        )

        if account is None:
            raise AccountNotFoundError from None

        return account

    def _fold(self, trades: Sequence[Trade]) -> Position:
        """Replay an instrument's trades into the position they leave.

        Cost is tracked on average, which is the method that needs no lot
        matching and the one most European tax regimes ask for. Every buy adds
        its cost and its fees to the pot; every sell takes out the share of the
        pot that belongs to the units leaving, and whatever the sale fetched
        above that share is a realised gain.

        Args:
            trades: The instrument's trades, oldest first.

        Returns:
            The units still held, what they cost, and what has been realised.
        """
        quantity_micro = 0
        cost_basis_minor = 0
        realised_gain_minor = 0

        for trade in trades:
            if trade.side == TradeSide.BUY:
                quantity_micro += trade.quantity_micro
                # Fees are part of what the units cost, so they reduce the gain
                # rather than disappearing. The same is true on the way out.
                cost_basis_minor += market_value_minor(trade.quantity_micro, trade.price_micro) + trade.fee_minor
                continue

            # Never more than is held. The write path refuses a trade that
            # would oversell, so this only ever bites on data that predates
            # that check, and clamping keeps a bad row from turning a whole
            # portfolio into nonsense.
            sold_micro = min(trade.quantity_micro, quantity_micro)
            cost_out_minor = apportion_minor(cost_basis_minor, sold_micro, quantity_micro)
            proceeds_minor = market_value_minor(sold_micro, trade.price_micro) - trade.fee_minor

            realised_gain_minor += proceeds_minor - cost_out_minor
            quantity_micro -= sold_micro
            cost_basis_minor -= cost_out_minor

        return Position(
            quantity_micro=quantity_micro,
            cost_basis_minor=cost_basis_minor,
            realised_gain_minor=realised_gain_minor,
        )

    def _require_position_stays_solvent(self, instrument: Instrument, added: Trade | None = None) -> None:
        """Check that no point in an instrument's history sells units it lacks.

        Checked over the whole history rather than at the moment of the sale,
        because a trade can be back-dated, corrected or removed after later
        ones already exist. Any of those can make a sale that was fine when it
        was recorded impossible, and the only way to see that is to replay.

        Args:
            instrument: The instrument whose history to replay.
            added: A trade not yet written, folded in at its place in the order.

        Raises:
            InsufficientUnitsError: If the running quantity ever goes negative.
        """
        history = list(
            self.trade_repository.history_for_instrument(
                instrument_id=instrument.id, household_id=instrument.household_id
            )
        )

        if added is not None:
            history.append(added)
            history.sort(key=_recorded_order)

        quantity_micro = 0
        for trade in history:
            if trade.side == TradeSide.BUY:
                quantity_micro += trade.quantity_micro
                continue

            quantity_micro -= trade.quantity_micro
            if quantity_micro < 0:
                self.session.rollback()
                raise InsufficientUnitsError(symbol=instrument.symbol) from None

    def _refresh_fx_rates(
        self,
        instruments: Sequence[Instrument],
        base_currency: str,
        cutoff: datetime.datetime,
    ) -> dict[str, str]:
        """Fetch and store the rates needed to value the portfolio.

        One rate per currency pair rather than per instrument: ten holdings in
        dollars need the dollar rate once. A pair fetched since the cutoff is
        left alone, on the same reasoning as a price, with one extra: the rates
        are a central bank's daily reference set, so asking twice in an hour
        cannot return anything new.

        Args:
            instruments: The household's instruments, already re-priced.
            base_currency: The currency the portfolio is reported in.
            cutoff: Rates stored at or after this moment are reused.

        Returns:
            A reason per pair that could not be fetched.
        """
        currencies = sorted({instrument.currency_code for instrument in instruments} - {base_currency})
        stored = self.fx_rate_repository.rates_into(quote_code=base_currency, base_codes=currencies)

        pairs: list[tuple[str, str]] = []
        for currency in currencies:
            row = stored.get(currency)
            # `updated_at` is None until a row is written a second time, so the
            # moment a rate was stored is whichever of the two the row has.
            fetched_at = None if row is None else (row.updated_at or row.created_at)

            if fetched_at is None or fetched_at < cutoff:
                pairs.append((currency, base_currency))

        if not pairs:
            return {}

        rates, failures = self.price_provider.fx_rates(pairs)

        for (from_code, to_code), rate in rates.items():
            self.fx_rate_repository.upsert(
                base_code=from_code, quote_code=to_code, rate_micro=rate.rate_micro, as_of=rate.as_of
            )

        return failures

    def _to_position(
        self, instrument: Instrument, folded: Position, rate_micro: int | None, is_open: bool
    ) -> PositionPublic:
        """Convert a folded position into the household's currency.

        Args:
            instrument: The instrument the position is in.
            folded: The position in the instrument's own currency.
            rate_micro: The rate into the household's currency, or None when
                no rate is known for that pair.
            is_open: Whether any units are still held.

        Returns:
            The position, as the API reports it.
        """
        priced = instrument.last_price_micro is not None and rate_micro is not None
        market_value = (
            convert_minor(market_value_minor(folded.quantity_micro, instrument.last_price_micro or 0), rate_micro or 0)
            if priced
            else None
        )
        # Without a rate there is no honest figure to give, so none is given.
        cost_basis = convert_minor(folded.cost_basis_minor, rate_micro) if rate_micro is not None else None

        return PositionPublic(
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            name=instrument.name,
            kind=instrument.kind,
            currency_code=instrument.currency_code,
            exchange=instrument.exchange,
            quantity_micro=folded.quantity_micro,
            is_open=is_open,
            last_price_micro=instrument.last_price_micro,
            last_price_at=instrument.last_price_at,
            last_price_is_manual=instrument.last_price_is_manual,
            fx_rate_micro=rate_micro,
            cost_basis_minor=cost_basis,
            market_value_minor=market_value,
            unrealised_gain_minor=(None if market_value is None or cost_basis is None else market_value - cost_basis),
            realised_gain_minor=(
                convert_minor(folded.realised_gain_minor, rate_micro) if rate_micro is not None else None
            ),
        )

    def _to_portfolio(
        self,
        currency_code: str,
        positions: list[PositionPublic],
        realised_gain_minor: int,
        unpriced_count: int,
    ) -> PortfolioPublic:
        """Total up the positions.

        Args:
            currency_code: The household's currency.
            positions: The positions to show, which may be a subset.
            realised_gain_minor: Realised gains across every position the
                household has, passed in rather than summed from `positions`
                because it must not change when closed ones are hidden.
            unpriced_count: How many positions could not be fully valued, over
                the same unfiltered set and for the same reason.

        Returns:
            The portfolio.
        """
        priced = [position for position in positions if position.market_value_minor is not None]
        as_of = [position.last_price_at for position in priced if position.last_price_at is not None]

        return PortfolioPublic(
            currency_code=currency_code,
            data=positions,
            count=len(positions),
            total_cost_basis_minor=sum(position.cost_basis_minor or 0 for position in positions),
            total_market_value_minor=sum(position.market_value_minor or 0 for position in priced),
            total_unrealised_gain_minor=sum(position.unrealised_gain_minor or 0 for position in priced),
            total_realised_gain_minor=realised_gain_minor,
            unpriced_count=unpriced_count,
            # The age of a total is the age of its stalest part, so the oldest
            # quote behind it is the one worth showing.
            priced_as_of=min(as_of) if as_of else None,
        )

    def _trades_by_instrument(self, household: HouseholdContext) -> dict[uuid.UUID, list[Trade]]:
        """Group the household's whole trade history by instrument.

        One query for the portfolio rather than one per holding.

        Args:
            household: The household context.

        Returns:
            A mapping of instrument ID to its trades, oldest first.
        """
        grouped: dict[uuid.UUID, list[Trade]] = {}

        for trade in self.trade_repository.history_for_household(household.household_id):
            grouped.setdefault(trade.instrument_id, []).append(trade)

        return grouped

    def _instruments_by_id(self, household: HouseholdContext) -> dict[uuid.UUID, Instrument]:
        """Load the household's instruments, keyed by ID.

        Args:
            household: The household context.

        Returns:
            A mapping of instrument ID to instrument.
        """
        instruments, _ = self.instrument_repository.list_for_household(
            household_id=household.household_id, limit=MAX_INSTRUMENTS
        )
        return {instrument.id: instrument for instrument in instruments}

    def _trade_to_public(self, trade: Trade, instrument: Instrument | None) -> TradePublic:
        """Build the public representation of a trade.

        Args:
            trade: The trade.
            instrument: The instrument it is against, if it could be loaded.

        Returns:
            The public trade.
        """
        return TradePublic.model_validate(
            trade,
            update={
                "symbol": instrument.symbol if instrument else "",
                "currency_code": instrument.currency_code if instrument else "EUR",
            },
        )

    def _household_currency(self, household: HouseholdContext) -> str:
        """Get the currency the household reports in.

        Args:
            household: The household context.

        Returns:
            The currency code.

        Raises:
            HouseholdNotFoundError: If the household no longer exists.
        """
        entity = self.household_repository.get_by_id(household.household_id)

        if not entity:
            raise HouseholdNotFoundError from None

        return entity.currency_code

    def _require_trade(self, household: HouseholdContext, trade_id: uuid.UUID) -> Trade:
        """Load a trade of the household.

        Args:
            household: The household context.
            trade_id: The ID of the trade.

        Returns:
            The trade.

        Raises:
            TradeNotFoundError: If it does not exist in the household.
        """
        trade = self.trade_repository.get_for_household(entity_id=trade_id, household_id=household.household_id)

        if not trade:
            raise TradeNotFoundError from None

        return trade

    def _require_symbol_is_free(self, household: HouseholdContext, symbol: str) -> None:
        """Check that the household does not already track a symbol.

        Args:
            household: The household context.
            symbol: The normalized ticker symbol.

        Raises:
            InstrumentExistsError: If it is already tracked.
        """
        if self.instrument_repository.get_by_symbol(household_id=household.household_id, symbol=symbol):
            raise InstrumentExistsError(symbol=symbol) from None

    def _normalize_symbol(self, symbol: str) -> str:
        """Put a ticker symbol into the one form it is stored and fetched in.

        Tickers are case insensitive to a person and case sensitive to a
        provider, so "vwce.de" and "VWCE.DE" have to become one thing before
        either the uniqueness check or the price lookup sees them.

        Args:
            symbol: The symbol as it was typed.

        Returns:
            The symbol, trimmed and upper cased.
        """
        return symbol.strip().upper()
