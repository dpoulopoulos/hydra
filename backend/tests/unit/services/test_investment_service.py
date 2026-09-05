import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.exceptions import (
    AccountNotFoundError,
    InstrumentExistsError,
    InstrumentInUseError,
    InstrumentNotFoundError,
    InstrumentNotPriceableError,
    InsufficientUnitsError,
    NotABrokerageAccountError,
    PriceProviderError,
    PriceProviderNotConfiguredError,
    TradeNotConvertibleError,
)
from app.models import (
    Account,
    AccountType,
    FxRate,
    Household,
    HouseholdContext,
    Instrument,
    InstrumentCreate,
    InstrumentKind,
    InstrumentPriceUpdate,
    SymbolMatch,
    Trade,
    TradeCreate,
    TradeSide,
)
from app.models.fields import MICRO
from app.services import InvestmentService
from app.services.prices import Quote

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTRUMENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def make_instrument(
    symbol: str = "VWCE.DE",
    currency_code: str = "EUR",
    last_price_micro: int | None = None,
    last_priced_at: datetime | None = None,
) -> Instrument:
    """Build an instrument row for the tests."""
    instrument = Instrument(
        household_id=HOUSEHOLD_ID,
        symbol=symbol,
        name="Vanguard FTSE All-World",
        kind=InstrumentKind.ETF,
        currency_code=currency_code,
        last_price_micro=last_price_micro,
        last_price_at=datetime(2026, 9, 4, 17, 30) if last_price_micro is not None else None,
        last_priced_at=last_priced_at,
    )
    instrument.id = INSTRUMENT_ID
    return instrument


def make_trade(
    side: TradeSide,
    units: int,
    price_major: int,
    fee_minor: int = 0,
    traded_on: date = date(2026, 1, 15),
    created_at: datetime | None = None,
) -> Trade:
    """Build a trade row for the tests, from whole units and a whole price."""
    trade = Trade(
        household_id=HOUSEHOLD_ID,
        instrument_id=INSTRUMENT_ID,
        side=side,
        traded_on=traded_on,
        quantity_micro=units * MICRO,
        # A whole major unit is a hundred minor ones, times MICRO.
        price_micro=price_major * 100 * MICRO,
        fee_minor=fee_minor,
    )
    trade.created_at = created_at or datetime(2026, 1, 15, 12, 0)
    return trade


def _trade_for(instrument_id: uuid.UUID, trade: Trade) -> Trade:
    """Point a built trade at another instrument."""
    trade.instrument_id = instrument_id
    return trade


@pytest.fixture
def household() -> Household:
    house = Household(name="Test household", currency_code="EUR")
    house.id = HOUSEHOLD_ID
    return house


class TestFoldPosition:
    """Tests for replaying trades into a position."""

    def test_a_single_buy(self, mock_investment_service: InvestmentService) -> None:
        """Test that one buy sets the quantity and the cost basis."""
        # Arrange: Set up a purchase of ten units at 100.00
        trades = [make_trade(TradeSide.BUY, units=10, price_major=100)]

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify ten units are held at a cost of 1000.00
        assert position.quantity_micro == 10 * MICRO
        assert position.cost_basis_minor == 100_000
        assert position.realised_gain_minor == 0

    def test_fees_are_part_of_what_the_units_cost(self, mock_investment_service: InvestmentService) -> None:
        """Test that a buy's fee is added to the cost basis rather than dropped."""
        # Arrange: Set up a purchase with a 5.00 commission
        trades = [make_trade(TradeSide.BUY, units=10, price_major=100, fee_minor=500)]

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify the fee raised the cost basis to 1005.00
        assert position.cost_basis_minor == 100_500

    def test_two_buys_average_their_cost(self, mock_investment_service: InvestmentService) -> None:
        """Test that buying at two prices pools the cost rather than keeping lots."""
        # Arrange: Set up ten units at 100.00 and ten more at 200.00
        trades = [
            make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
            make_trade(TradeSide.BUY, units=10, price_major=200, traded_on=date(2026, 2, 1)),
        ]

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify twenty units are held at a pooled cost of 3000.00
        assert position.quantity_micro == 20 * MICRO
        assert position.cost_basis_minor == 300_000

    def test_a_sell_realises_the_gain_above_average_cost(self, mock_investment_service: InvestmentService) -> None:
        """Test that selling above the average cost realises the difference."""
        # Arrange: Set up a purchase at 100.00 and a sale of half at 150.00
        trades = [
            make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
            make_trade(TradeSide.SELL, units=5, price_major=150, traded_on=date(2026, 3, 1)),
        ]

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify five units remain, holding half the original cost, and
        # the 250.00 made on the sale is realised
        assert position.quantity_micro == 5 * MICRO
        assert position.cost_basis_minor == 50_000
        assert position.realised_gain_minor == 25_000

    def test_a_sell_fee_reduces_the_realised_gain(self, mock_investment_service: InvestmentService) -> None:
        """Test that a sale's fee comes off what the sale actually made."""
        # Arrange: Set up the same sale, with a 10.00 commission on the way out
        trades = [
            make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
            make_trade(TradeSide.SELL, units=5, price_major=150, fee_minor=1_000, traded_on=date(2026, 3, 1)),
        ]

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify the gain is 250.00 less the 10.00 fee
        assert position.realised_gain_minor == 24_000

    def test_selling_at_a_loss_realises_a_negative_gain(self, mock_investment_service: InvestmentService) -> None:
        """Test that a loss is carried as a negative rather than clamped to zero."""
        # Arrange: Set up a purchase at 100.00 and a sale of all of it at 60.00
        trades = [
            make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
            make_trade(TradeSide.SELL, units=10, price_major=60, traded_on=date(2026, 3, 1)),
        ]

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify the position is empty and 400.00 was lost
        assert position.quantity_micro == 0
        assert position.cost_basis_minor == 0
        assert position.realised_gain_minor == -40_000

    def test_selling_out_completely_leaves_no_cost_behind(self, mock_investment_service: InvestmentService) -> None:
        """Test that a position sold in pieces ends with no stranded cost basis.

        This is what rounding the apportioned share buys: truncating would leave
        a few cents of cost behind on the last sale, which reads as a gain that
        was never made.
        """
        # Arrange: Set up a purchase whose cost does not divide evenly by three
        trades = [make_trade(TradeSide.BUY, units=3, price_major=100, fee_minor=1)]
        for month in (2, 3, 4):
            trades.append(make_trade(TradeSide.SELL, units=1, price_major=100, traded_on=date(2026, month, 1)))

        # Act: Fold the history
        position = mock_investment_service._fold(trades)

        # Assert: Verify nothing is held and no cost is stranded
        assert position.quantity_micro == 0
        assert position.cost_basis_minor == 0

    def test_no_trades_is_an_empty_position(self, mock_investment_service: InvestmentService) -> None:
        """Test that an instrument never traded folds to nothing rather than failing."""
        # Arrange & Act: Fold an empty history
        position = mock_investment_service._fold([])

        # Assert: Verify everything is zero
        assert position.quantity_micro == 0
        assert position.cost_basis_minor == 0
        assert position.realised_gain_minor == 0


class TestCreateTrade:
    """Tests for recording a buy or a sell."""

    def test_records_a_buy(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        # Arrange: Set up an instrument with no history behind it
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.history_for_instrument = MagicMock(return_value=[])

        # Act: Record a purchase of ten units
        result = mock_investment_service.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.BUY,
                traded_on=date(2026, 1, 15),
                quantity_micro=10 * MICRO,
                price_micro=10_000 * MICRO,
            ),
        )

        # Assert: Verify the trade was saved against the household's instrument
        assert result.side == TradeSide.BUY
        assert result.symbol == "VWCE.DE"
        assert result.currency_code == "EUR"
        mock_investment_service.session.commit.assert_called_once()

    def test_refuses_to_sell_units_the_household_does_not_hold(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that overselling is refused rather than stored as a negative position."""
        # Arrange: Set up an instrument holding five units
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.history_for_instrument = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=5, price_major=100)]
        )

        # Act & Assert: Verify selling ten of them is refused
        with pytest.raises(InsufficientUnitsError):
            mock_investment_service.create_trade(
                household=household_context,
                trade_create=TradeCreate(
                    instrument_id=INSTRUMENT_ID,
                    side=TradeSide.SELL,
                    traded_on=date(2026, 3, 1),
                    quantity_micro=10 * MICRO,
                    price_micro=10_000 * MICRO,
                ),
            )

    def test_refuses_a_back_dated_sale_that_precedes_its_units(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that the check replays the history rather than looking at today.

        The household ends up holding enough units, so a check that only looked
        at the final total would allow this. On the day of the sale it held
        none, which is what makes it wrong.
        """
        # Arrange: Set up a purchase made in March
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.history_for_instrument = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 3, 1))]
        )

        # Act & Assert: Verify a sale dated before it is refused
        with pytest.raises(InsufficientUnitsError):
            mock_investment_service.create_trade(
                household=household_context,
                trade_create=TradeCreate(
                    instrument_id=INSTRUMENT_ID,
                    side=TradeSide.SELL,
                    traded_on=date(2026, 1, 1),
                    quantity_micro=5 * MICRO,
                    price_micro=10_000 * MICRO,
                ),
            )

    def test_rejects_an_instrument_from_another_household(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that an instrument outside the household is reported as missing."""
        # Arrange: Set up a scoped lookup that finds nothing
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=None)

        # Act & Assert: Verify it is a 404 rather than a leak that the ID exists
        with pytest.raises(InstrumentNotFoundError):
            mock_investment_service.create_trade(
                household=household_context,
                trade_create=TradeCreate(
                    instrument_id=INSTRUMENT_ID,
                    side=TradeSide.BUY,
                    traded_on=date(2026, 1, 15),
                    quantity_micro=MICRO,
                    price_micro=MICRO,
                ),
            )


class TestCreateInstrument:
    """Tests for starting to track an instrument."""

    def test_takes_the_currency_and_price_from_the_first_quote(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that the provider settles the currency rather than the caller."""
        # Arrange: Set up a provider that knows the symbol and quotes it in dollars
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)
        mock_price_provider.quotes.return_value = (
            {
                "VOO": Quote(
                    symbol="VOO",
                    price_micro=50_000 * MICRO,
                    currency_code="USD",
                    exchange="NYSEArca",
                    as_of=datetime(2026, 9, 4, 20, 0),
                )
            },
            {},
        )

        # Act: Track the instrument without saying what it quotes in
        result = mock_investment_service.create_instrument(
            household=household_context,
            instrument_create=InstrumentCreate(symbol="voo", name="Vanguard S&P 500"),
        )

        # Assert: Verify the quote settled the currency, the exchange and the price
        assert result.currency_code == "USD"
        assert result.exchange == "NYSEArca"
        assert result.last_price_micro == 50_000 * MICRO

    def test_normalizes_the_symbol_before_storing_it(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a lower case ticker is stored the way it is fetched."""
        # Arrange: Set up a provider that knows nothing, and a supplied currency
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)

        # Act: Track an instrument typed in lower case with spaces around it
        result = mock_investment_service.create_instrument(
            household=household_context,
            instrument_create=InstrumentCreate(
                symbol="  vwce.de  ", name="Vanguard FTSE All-World", currency_code="EUR"
            ),
        )

        # Assert: Verify it was trimmed and upper cased
        assert result.symbol == "VWCE.DE"

    def test_a_supplied_currency_lets_an_unknown_symbol_through(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that saying what it is worth measuring in is enough to track it by hand."""
        # Arrange: Set up a provider that does not know the symbol
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)

        # Act: Track it anyway, with a currency
        result = mock_investment_service.create_instrument(
            household=household_context,
            instrument_create=InstrumentCreate(symbol="PRIVATE.FUND", name="A fund nobody quotes", currency_code="EUR"),
        )

        # Assert: Verify it was stored with no price rather than refused
        assert result.currency_code == "EUR"
        assert result.last_price_micro is None

    def test_an_unknown_symbol_with_no_currency_is_refused(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that a symbol nothing can price is not given a guessed currency."""
        # Arrange: Set up a provider that does not know the symbol
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)

        # Act & Assert: Verify the caller is told rather than the currency guessed
        with pytest.raises(InstrumentNotPriceableError):
            mock_investment_service.create_instrument(
                household=household_context,
                instrument_create=InstrumentCreate(symbol="TYPO.XX", name="A typo"),
            )

    def test_rejects_a_symbol_the_household_already_tracks(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        # Arrange: Set up a household that already tracks the symbol
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=make_instrument())

        # Act & Assert: Verify the duplicate is a conflict
        with pytest.raises(InstrumentExistsError):
            mock_investment_service.create_instrument(
                household=household_context,
                instrument_create=InstrumentCreate(symbol="VWCE.DE", name="Duplicate", currency_code="EUR"),
            )

    def test_market_data_switched_off_still_allows_a_manual_instrument(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that no provider does not mean no investments section."""
        # Arrange: Set up a deployment with market data switched off
        mock_price_provider.is_configured = False
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)

        # Act: Track an instrument with its currency given
        result = mock_investment_service.create_instrument(
            household=household_context,
            instrument_create=InstrumentCreate(symbol="VWCE.DE", name="By hand", currency_code="EUR"),
        )

        # Assert: Verify it was stored, unpriced
        assert result.last_price_micro is None

    def test_market_data_switched_off_refuses_to_guess_a_currency(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        # Arrange: Set up a deployment with market data switched off
        mock_price_provider.is_configured = False
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)

        # Act & Assert: Verify the caller is told the feature is off
        with pytest.raises(PriceProviderNotConfiguredError):
            mock_investment_service.create_instrument(
                household=household_context,
                instrument_create=InstrumentCreate(symbol="VWCE.DE", name="No currency"),
            )


class TestDeleteInstrument:
    """Tests for removing an instrument."""

    def test_refuses_while_it_still_has_trades(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that history is not silently thrown away with the instrument."""
        # Arrange: Set up an instrument with trades behind it
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=make_instrument())
        mock_investment_service.trade_repository.count_for_instrument = MagicMock(return_value=3)

        # Act & Assert: Verify the delete is refused
        with pytest.raises(InstrumentInUseError):
            mock_investment_service.delete_instrument(household=household_context, instrument_id=INSTRUMENT_ID)


class TestGetPortfolio:
    """Tests for valuing the whole portfolio."""

    def test_values_a_holding_in_the_household_currency(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        # Arrange: Set up ten units bought at 100.00, now quoted at 120.00
        instrument = make_instrument(last_price_micro=12_000 * MICRO)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=10, price_major=100)]
        )
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})

        # Act: Value the portfolio
        portfolio = mock_investment_service.get_portfolio(household=household_context)

        # Assert: Verify the holding is worth 1200.00 against a cost of 1000.00
        assert portfolio.currency_code == "EUR"
        assert portfolio.count == 1
        assert portfolio.total_market_value_minor == 120_000
        assert portfolio.total_cost_basis_minor == 100_000
        assert portfolio.total_unrealised_gain_minor == 20_000
        assert portfolio.unpriced_count == 0

    def test_converts_a_foreign_holding_at_the_stored_rate(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that a dollar listing is reported in the household's euro."""
        # Arrange: Set up ten units bought and quoted at 100.00 dollars, at 0.90
        instrument = make_instrument(symbol="VOO", currency_code="USD", last_price_micro=10_000 * MICRO)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=10, price_major=100)]
        )
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(
            return_value={"USD": FxRate(base_code="USD", quote_code="EUR", rate_micro=900_000, as_of=datetime.now(UTC))}
        )

        # Act: Value the portfolio
        portfolio = mock_investment_service.get_portfolio(household=household_context)

        # Assert: Verify 1000.00 dollars is reported as 900.00 euro, and the
        # price stays in the currency the exchange actually quoted
        assert portfolio.total_market_value_minor == 90_000
        assert portfolio.data[0].currency_code == "USD"
        assert portfolio.data[0].last_price_micro == 10_000 * MICRO
        assert portfolio.data[0].fx_rate_micro == 900_000

    def test_a_holding_with_no_rate_is_unvalued_rather_than_worthless(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that a missing rate leaves the value absent instead of zero.

        Zero would be read as "worth nothing", which is a very different claim
        from "not known yet".
        """
        # Arrange: Set up a dollar holding with no stored rate to convert it
        instrument = make_instrument(symbol="VOO", currency_code="USD", last_price_micro=10_000 * MICRO)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=10, price_major=100)]
        )
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})

        # Act: Value the portfolio
        portfolio = mock_investment_service.get_portfolio(household=household_context)

        # Assert: Verify the position is reported as unpriced
        assert portfolio.data[0].market_value_minor is None
        assert portfolio.unpriced_count == 1
        assert portfolio.total_market_value_minor == 0

    def test_an_unpriced_holding_does_not_understate_the_total_silently(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that a holding never quoted is counted as unpriced."""
        # Arrange: Set up an instrument with no price fetched yet
        instrument = make_instrument(last_price_micro=None)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=10, price_major=100)]
        )
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})

        # Act: Value the portfolio
        portfolio = mock_investment_service.get_portfolio(household=household_context)

        # Assert: Verify the cost is still known but the value is not
        assert portfolio.total_cost_basis_minor == 100_000
        assert portfolio.unpriced_count == 1

    def test_a_closed_position_is_hidden_unless_asked_for(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that a position sold out is kept for its realised gain."""
        # Arrange: Set up a holding bought and then sold in full at a profit
        instrument = make_instrument(last_price_micro=12_000 * MICRO)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[
                make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
                make_trade(TradeSide.SELL, units=10, price_major=150, traded_on=date(2026, 3, 1)),
            ]
        )
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})

        # Act: Value the portfolio both ways
        open_only = mock_investment_service.get_portfolio(household=household_context)
        with_closed = mock_investment_service.get_portfolio(household=household_context, include_closed=True)

        # Assert: Verify it is hidden by default and its gain survives when asked for
        assert open_only.count == 0
        assert with_closed.count == 1
        assert with_closed.data[0].is_open is False
        assert with_closed.total_realised_gain_minor == 50_000


class TestRefreshPrices:
    """Tests for fetching fresh prices."""

    def test_stores_the_fetched_price_on_the_instrument(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        # Arrange: Set up an instrument and a provider that quotes it
        instrument = make_instrument()
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_price_provider.quotes.return_value = (
            {
                "VWCE.DE": Quote(
                    symbol="VWCE.DE",
                    price_micro=12_845 * MICRO,
                    currency_code="EUR",
                    exchange="XETRA",
                    as_of=datetime(2026, 9, 4, 17, 30),
                )
            },
            {},
        )

        # Act: Refresh the prices
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the price landed on the row and nothing failed
        assert result.updated_count == 1
        assert result.failures == []
        assert instrument.last_price_micro == 12_845 * MICRO
        mock_investment_service.session.commit.assert_called_once()

    def test_one_bad_symbol_does_not_stop_the_others(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a delisted ticker is reported rather than raised."""
        # Arrange: Set up two instruments, one of which the provider rejects
        good = make_instrument()
        bad = make_instrument(symbol="GONE.XX")
        bad.id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([good, bad], 2))
        mock_price_provider.quotes.return_value = (
            {
                "VWCE.DE": Quote(
                    symbol="VWCE.DE",
                    price_micro=12_845 * MICRO,
                    currency_code="EUR",
                    exchange="XETRA",
                    as_of=datetime(2026, 9, 4, 17, 30),
                )
            },
            {"GONE.XX": "The provider does not know this symbol."},
        )

        # Act: Refresh the prices
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the good one was priced and the bad one was reported
        assert result.updated_count == 1
        assert [failure.symbol for failure in result.failures] == ["GONE.XX"]
        assert good.last_price_micro == 12_845 * MICRO

    def test_fetches_one_rate_per_currency_rather_than_per_holding(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that ten dollar holdings ask for the dollar rate once."""
        # Arrange: Set up two dollar holdings and one in the household currency
        instruments = []
        for index, (symbol, currency) in enumerate([("VOO", "USD"), ("QQQ", "USD"), ("VWCE.DE", "EUR")]):
            instrument = make_instrument(symbol=symbol, currency_code=currency)
            instrument.id = uuid.UUID(int=index + 1)
            instruments.append(instrument)

        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=(instruments, 3))
        mock_investment_service.fx_rate_repository.upsert = MagicMock()

        # Act: Refresh the prices
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify only the dollar pair was asked for, once
        mock_price_provider.fx_rates.assert_called_once_with([("USD", "EUR")])

    def test_refuses_when_market_data_is_switched_off(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        # Arrange: Set up a deployment with market data switched off
        mock_price_provider.is_configured = False

        # Act & Assert: Verify the caller is told, rather than seeing an empty refresh
        with pytest.raises(PriceProviderNotConfiguredError):
            mock_investment_service.refresh_prices(household=household_context)


class TestPriceCache:
    """Tests for reusing a stored price instead of spending an API call.

    The provider bills one call per symbol and a free plan allows twenty a day,
    so what is *not* fetched is the load-bearing part of a refresh.
    """

    def test_a_price_fetched_moments_ago_is_not_fetched_again(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a second refresh inside the window costs nothing."""
        # Arrange: Set up an instrument priced one minute ago
        recent = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        instrument = make_instrument(last_price_micro=12_845 * MICRO, last_priced_at=recent)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))

        # Act: Refresh again
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the provider was never called and the reuse was reported
        mock_price_provider.quotes.assert_not_called()
        assert result.updated_count == 0
        assert result.cached_count == 1
        assert instrument.last_price_micro == 12_845 * MICRO

    def test_a_price_older_than_the_window_is_fetched(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that the cache expires rather than pinning a stale price forever."""
        # Arrange: Set up an instrument priced three hours ago, past the two hour window
        stale = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
        instrument = make_instrument(last_price_micro=12_845 * MICRO, last_priced_at=stale)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_price_provider.quotes.return_value = (
            {
                "VWCE.DE": Quote(
                    symbol="VWCE.DE",
                    price_micro=13_000 * MICRO,
                    currency_code="EUR",
                    exchange="XETRA",
                    as_of=datetime(2026, 9, 5, 17, 30),
                )
            },
            {},
        )

        # Act: Refresh
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the new price replaced the old one
        assert result.updated_count == 1
        assert result.cached_count == 0
        assert instrument.last_price_micro == 13_000 * MICRO

    def test_only_the_stale_holdings_are_asked_about(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a mixed portfolio spends a call only on what has gone stale.

        This is where the budget is won: nine fresh holdings and one stale one
        should cost one API call, not ten.
        """
        # Arrange: Set up one fresh instrument and one stale one
        now = datetime.now(UTC).replace(tzinfo=None)
        fresh = make_instrument(symbol="VWCE.DE", last_priced_at=now - timedelta(minutes=5))
        stale = make_instrument(symbol="VOO.US", currency_code="USD", last_priced_at=now - timedelta(days=1))
        stale.id = uuid.UUID("44444444-4444-4444-4444-444444444444")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([fresh, stale], 2))
        mock_price_provider.quotes.return_value = ({}, {})

        # Act: Refresh
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify only the stale symbol was sent
        symbols, kwargs = mock_price_provider.quotes.call_args
        assert list(symbols[0]) == ["VOO.US"]
        assert result.cached_count == 1

    def test_the_stored_currency_travels_with_the_request(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a provider which reports no currency is told what one to use."""
        # Arrange: Set up a dollar instrument that has never been priced
        instrument = make_instrument(symbol="VOO.US", currency_code="USD")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_price_provider.quotes.return_value = ({}, {})

        # Act: Refresh
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the stored currency was handed over
        assert mock_price_provider.quotes.call_args.kwargs["currencies"] == {"VOO.US": "USD"}

    def test_a_failed_symbol_is_not_put_behind_the_cache(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a failure can be retried at once rather than in two hours.

        Recording the attempt would make the retry button do nothing, which is
        worse than spending the call the person chose to spend.
        """
        # Arrange: Set up an instrument the provider refuses
        instrument = make_instrument()
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_price_provider.quotes.return_value = ({}, {"VWCE.DE": "The provider does not know this symbol."})

        # Act: Refresh
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify nothing marked it as recently asked about
        assert instrument.last_priced_at is None

    def test_a_rate_stored_inside_the_window_is_not_fetched_again(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a recent exchange rate is reused."""
        # Arrange: Set up a dollar holding and a dollar rate stored a minute ago
        instrument = make_instrument(
            symbol="VOO.US", currency_code="USD", last_priced_at=datetime.now(UTC).replace(tzinfo=None)
        )
        rate = FxRate(base_code="USD", quote_code="EUR", rate_micro=900_000, as_of=datetime(2026, 9, 5, 0, 0))
        rate.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={"USD": rate})

        # Act: Refresh
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify no rate was fetched
        mock_price_provider.fx_rates.assert_not_called()

    def test_a_rate_older_than_the_window_is_fetched(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a day-old rate is refreshed."""
        # Arrange: Set up a dollar holding and a rate stored yesterday
        instrument = make_instrument(
            symbol="VOO.US", currency_code="USD", last_priced_at=datetime.now(UTC).replace(tzinfo=None)
        )
        rate = FxRate(base_code="USD", quote_code="EUR", rate_micro=900_000, as_of=datetime(2026, 9, 4, 0, 0))
        rate.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={"USD": rate})
        mock_price_provider.fx_rates.return_value = ({}, {})

        # Act: Refresh
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the pair was asked for
        assert mock_price_provider.fx_rates.call_args[0][0] == [("USD", "EUR")]


class TestCreateInstrumentWithoutTheProvider:
    """Tests for adding a holding when the provider is metered or down."""

    def test_a_supplied_currency_means_the_provider_is_never_called(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that adding a holding can cost nothing.

        The symbol search the caller just used already reported the currency,
        so sending it back saves an API call, and adding a row to a list should
        not depend on a website being up.
        """
        # Arrange: Set up a free symbol
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)

        # Act: Track it with the currency in hand
        result = mock_investment_service.create_instrument(
            household=household_context,
            instrument_create=InstrumentCreate(symbol="vuaa.xetra", name="Vanguard S&P 500", currency_code="EUR"),
        )

        # Assert: Verify nothing was fetched
        mock_price_provider.quotes.assert_not_called()
        mock_price_provider.search.assert_not_called()
        assert result.currency_code == "EUR"
        assert result.last_price_micro is None

    def test_the_currency_is_looked_up_when_it_was_not_supplied(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that the search index settles the currency for a provider whose quotes omit it."""
        # Arrange: Set up a search that knows the listing
        mock_investment_service.instrument_repository.get_by_symbol = MagicMock(return_value=None)
        mock_price_provider.search.return_value = [
            SymbolMatch(
                symbol="VUAA.XETRA",
                name="Vanguard S&P 500 UCITS ETF",
                currency_code="EUR",
                exchange="XETRA",
                kind=InstrumentKind.ETF,
            )
        ]

        # Act: Track it without saying what it quotes in
        result = mock_investment_service.create_instrument(
            household=household_context,
            instrument_create=InstrumentCreate(symbol="vuaa.xetra", name="Vanguard S&P 500"),
        )

        # Assert: Verify the search answered and no quote was needed
        assert result.currency_code == "EUR"
        assert result.exchange == "XETRA"
        mock_price_provider.quotes.assert_not_called()


class TestListInstruments:
    """Tests for the list of instruments a household tracks."""

    def test_it_lists_an_instrument_that_has_never_been_traded(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that a tracked but untraded instrument appears.

        The portfolio deliberately hides these, because they are not a holding.
        That leaves them reachable nowhere else, so this list is the only place
        someone can see one and stop tracking it.
        """
        # Arrange: Set up an instrument with no trades against it
        instrument = make_instrument()
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.counts_by_instrument = MagicMock(return_value={})

        # Act: List the instruments
        result = mock_investment_service.list_instruments(household=household_context)

        # Assert: Verify it is listed, and shown as free to delete
        assert result.count == 1
        assert result.data[0].symbol == "VWCE.DE"
        assert result.data[0].trade_count == 0

    def test_it_reports_how_many_trades_hold_an_instrument_down(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that the trade count travels with the row.

        Deleting an instrument with trades is refused, so a list that offers
        the button without saying why it will fail is worse than no button.
        """
        # Arrange: Set up an instrument with three trades against it
        instrument = make_instrument()
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.trade_repository.counts_by_instrument = MagicMock(return_value={instrument.id: 3})

        # Act: List the instruments
        result = mock_investment_service.list_instruments(household=household_context)

        # Assert: Verify the count came through
        assert result.data[0].trade_count == 3

    def test_the_counts_cost_one_query_for_the_whole_page(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that counting is grouped rather than done once per row."""
        # Arrange: Set up three instruments
        instruments = []
        for index, symbol in enumerate(("AAA.DE", "BBB.DE", "CCC.DE")):
            instrument = make_instrument(symbol=symbol)
            instrument.id = uuid.UUID(f"5555555{index}-5555-5555-5555-555555555555")
            instruments.append(instrument)

        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=(instruments, 3))
        counts = MagicMock(return_value={})
        mock_investment_service.trade_repository.counts_by_instrument = counts

        # Act: List them
        mock_investment_service.list_instruments(household=household_context)

        # Assert: Verify one grouped call served all three rows
        counts.assert_called_once()


class TestListFxRates:
    """Tests for showing the rates behind the converted figures."""

    def test_it_reports_the_rate_and_both_of_its_dates(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that the day a rate refers to is reported apart from when it was fetched.

        A Friday rate fetched on Monday is neither wrong nor fresh, and only
        showing both dates makes that legible.
        """
        # Arrange: Set up a dollar holding and a rate published before it was stored
        instrument = make_instrument(symbol="VOO.US", currency_code="USD")
        rate = FxRate(base_code="USD", quote_code="EUR", rate_micro=860_440, as_of=datetime(2026, 9, 4))
        rate.created_at = datetime(2026, 9, 7, 9, 0)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.list_into = MagicMock(return_value=[rate])

        # Act: List the rates
        result = mock_investment_service.list_fx_rates(household=household_context)

        # Assert: Verify both dates and the direction of the pair
        assert result.quote_code == "EUR"
        assert result.data[0].base_code == "USD"
        assert result.data[0].rate_micro == 860_440
        assert result.data[0].as_of == datetime(2026, 9, 4)
        assert result.data[0].fetched_at == datetime(2026, 9, 7, 9, 0)
        assert result.data[0].in_use is True
        assert result.missing == []

    def test_a_rate_for_something_no_longer_held_is_kept_but_marked(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that a leftover rate is shown as unused rather than hidden.

        Hiding it would make a figure that was converted before the last sale
        look as though it came from nowhere.
        """
        # Arrange: Set up a euro-only portfolio and a stored dollar rate
        instrument = make_instrument(currency_code="EUR")
        rate = FxRate(base_code="USD", quote_code="EUR", rate_micro=860_440, as_of=datetime(2026, 9, 4))
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.list_into = MagicMock(return_value=[rate])

        # Act: List the rates
        result = mock_investment_service.list_fx_rates(household=household_context)

        # Assert: Verify it is present and flagged
        assert result.count == 1
        assert result.data[0].in_use is False

    def test_a_currency_held_with_no_rate_is_named(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that an unconvertible holding says which currency is missing.

        That holding cannot be valued at all, and the fix is per currency, so a
        count would not be enough to act on.
        """
        # Arrange: Set up a dollar holding with no dollar rate stored
        instrument = make_instrument(symbol="VOO.US", currency_code="USD")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.list_into = MagicMock(return_value=[])

        # Act: List the rates
        result = mock_investment_service.list_fx_rates(household=household_context)

        # Assert: Verify the gap is named
        assert result.missing == ["USD"]

    def test_the_household_currency_needs_no_rate_of_its_own(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
    ) -> None:
        """Test that euro into euro is never reported as missing."""
        # Arrange: Set up a euro-only portfolio in a euro household
        instrument = make_instrument(currency_code="EUR")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.list_into = MagicMock(return_value=[])

        # Act: List the rates
        result = mock_investment_service.list_fx_rates(household=household_context)

        # Assert: Verify nothing is wanted
        assert result.missing == []
        assert result.count == 0


class TestSetInstrumentPrice:
    """Tests for typing a price in by hand."""

    def test_it_stores_the_price_and_marks_it_as_typed(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that a hand-entered price is stored and labelled honestly.

        A number someone typed and a number a market reported are both useful
        and are not the same claim, so the row records which it holds.
        """
        # Arrange: Set up an instrument with no price
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.count_for_instrument = MagicMock(return_value=0)

        # Act: Type in a price
        result = mock_investment_service.set_instrument_price(
            household=household_context,
            instrument_id=instrument.id,
            price_update=InstrumentPriceUpdate(price_micro=12_500 * MICRO),
        )

        # Assert: Verify it landed and is flagged as typed
        assert result.last_price_micro == 12_500 * MICRO
        assert result.last_price_is_manual is True

    def test_it_counts_as_fresh_so_no_api_call_is_spent_replacing_it(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a typed price puts the instrument inside the cache window.

        The app now has a current price, so asking the provider for another
        would spend one of a small daily allowance to learn nothing.
        """
        # Arrange: Type a price in
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.count_for_instrument = MagicMock(return_value=0)
        mock_investment_service.set_instrument_price(
            household=household_context,
            instrument_id=instrument.id,
            price_update=InstrumentPriceUpdate(price_micro=12_500 * MICRO),
        )

        # Act: Refresh straight afterwards
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the provider was left alone
        mock_price_provider.quotes.assert_not_called()
        assert result.cached_count == 1

    def test_a_fetched_price_supersedes_a_typed_one(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that the typed flag clears when a real quote arrives.

        The flag describes the price sitting on the row, so it has to move when
        that price does. A stale flag would label a fetched price as invented.
        """
        # Arrange: Set up an instrument holding a typed price from long ago
        instrument = make_instrument(
            last_price_micro=12_500 * MICRO,
            last_priced_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
        )
        instrument.last_price_is_manual = True
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_price_provider.quotes.return_value = (
            {
                "VWCE.DE": Quote(
                    symbol="VWCE.DE",
                    price_micro=13_000 * MICRO,
                    currency_code="EUR",
                    exchange="XETRA",
                    as_of=datetime(2026, 9, 5, 17, 30),
                )
            },
            {},
        )

        # Act: Refresh
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify both the price and the label moved
        assert instrument.last_price_micro == 13_000 * MICRO
        assert instrument.last_price_is_manual is False

    def test_an_unknown_instrument_is_refused(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that pricing something in another household is a 404, not a write."""
        # Arrange: Set up a repository that finds nothing in this household
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=None)

        # Act & Assert: Verify it is refused
        with pytest.raises(InstrumentNotFoundError):
            mock_investment_service.set_instrument_price(
                household=household_context,
                instrument_id=uuid.uuid4(),
                price_update=InstrumentPriceUpdate(price_micro=100 * MICRO),
            )


class TestTradeCashSide:
    """Tests for a trade moving cash through a brokerage account.

    No ledger row is written. A brokerage balance is folded from its trades as
    well as its transactions, so buying takes cash out of it and selling puts
    cash in, exactly as a broker's statement shows. Money reaching the broker in
    the first place is an ordinary transfer that someone records themselves.
    """

    @pytest.fixture
    def broker_account(self) -> Account:
        account = Account(
            household_id=HOUSEHOLD_ID,
            name="Degiro",
            type=AccountType.BROKERAGE,
            currency_code="EUR",
            opening_balance_minor=0,
            opening_balance_date=date(2025, 1, 1),
        )
        account.id = uuid.UUID("77777777-7777-7777-7777-777777777777")
        return account

    @pytest.fixture
    def wired(
        self,
        mock_investment_service: InvestmentService,
        household: Household,
        broker_account: Account,
    ) -> InvestmentService:
        """A service whose accounts are stubbed, ready to record a trade."""
        instrument = make_instrument()
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.history_for_instrument = MagicMock(return_value=[])
        mock_investment_service.account_repository.get_for_household = MagicMock(return_value=broker_account)
        return mock_investment_service

    def test_a_buy_records_what_it_took_out_of_the_broker(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that a buy stores the cash it consumed, fee included."""
        # Act: Buy 10 units at 100.00 with a 1.50 fee
        result = wired.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.BUY,
                traded_on=date(2026, 3, 1),
                quantity_micro=10 * MICRO,
                price_micro=100 * 100 * MICRO,
                fee_minor=150,
                brokerage_account_id=broker_account.id,
            ),
        )

        # Assert: Verify the cash is recorded on the trade itself
        assert result.cash_amount_minor == 100_150
        assert result.brokerage_account_id == broker_account.id

    def test_a_sell_records_what_it_put_back_after_the_fee(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that a sale nets the fee off its proceeds."""
        # Arrange: Set up a holding to sell out of
        wired.trade_repository.history_for_instrument = MagicMock(
            return_value=[make_trade(TradeSide.BUY, units=10, price_major=100)]
        )

        # Act: Sell 4 units at 120.00 with a 1.50 fee
        result = wired.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.SELL,
                traded_on=date(2026, 3, 1),
                quantity_micro=4 * MICRO,
                price_micro=120 * 100 * MICRO,
                fee_minor=150,
                brokerage_account_id=broker_account.id,
            ),
        )

        # Assert: Verify 480.00 less the fee
        assert result.cash_amount_minor == 47_850

    def test_a_supplied_cash_amount_beats_the_calculation(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that what the broker charged wins over what the app works out.

        No conversion this app can do will match a broker's rate on the day, so
        a figure someone read off a statement is the better answer.
        """
        # Act: Record a buy with the exact amount the broker took
        result = wired.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.BUY,
                traded_on=date(2026, 3, 1),
                quantity_micro=10 * MICRO,
                price_micro=100 * 100 * MICRO,
                fee_minor=150,
                brokerage_account_id=broker_account.id,
                cash_amount_minor=99_999,
            ),
        )

        # Assert: Verify the supplied figure was used untouched
        assert result.cash_amount_minor == 99_999

    def test_a_trade_with_no_account_moves_no_cash(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that the cash side stays optional.

        A trade is a fact about a holding whether or not the money is tracked
        here, and every trade recorded before this feature existed has none.
        """
        # Act: Record a trade without naming a brokerage account
        result = wired.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.BUY,
                traded_on=date(2026, 3, 1),
                quantity_micro=10 * MICRO,
                price_micro=100 * 100 * MICRO,
            ),
        )

        # Assert: Verify no cash side was recorded
        assert result.brokerage_account_id is None
        assert result.cash_amount_minor is None

    def test_a_free_share_costs_nothing(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that a zero-cost grant takes no cash out of the broker."""
        # Act: Record an employer grant at no cost
        result = wired.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.BUY,
                traded_on=date(2026, 3, 1),
                quantity_micro=1 * MICRO,
                price_micro=0,
                fee_minor=0,
                brokerage_account_id=broker_account.id,
            ),
        )

        # Assert: Verify it moved nothing
        assert result.cash_amount_minor == 0

    def test_a_foreign_trade_with_no_rate_says_so_rather_than_guessing(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that an unconvertible trade is refused with a fix, not a made-up number."""
        # Arrange: Set up a dollar instrument and no stored dollar rate
        wired.instrument_repository.get_for_household = MagicMock(
            return_value=make_instrument(symbol="VOO.US", currency_code="USD")
        )
        wired.fx_rate_repository.rates_into = MagicMock(return_value={})

        # Act & Assert: Verify it is refused
        with pytest.raises(TradeNotConvertibleError):
            wired.create_trade(
                household=household_context,
                trade_create=TradeCreate(
                    instrument_id=INSTRUMENT_ID,
                    side=TradeSide.BUY,
                    traded_on=date(2026, 3, 1),
                    quantity_micro=10 * MICRO,
                    price_micro=100 * 100 * MICRO,
                    brokerage_account_id=broker_account.id,
                ),
            )

    def test_a_foreign_trade_converts_at_the_stored_rate(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that a dollar trade records the right number of euros."""
        # Arrange: Set up a dollar instrument and a 0.90 rate
        wired.instrument_repository.get_for_household = MagicMock(
            return_value=make_instrument(symbol="VOO.US", currency_code="USD")
        )
        wired.fx_rate_repository.rates_into = MagicMock(
            return_value={
                "USD": FxRate(base_code="USD", quote_code="EUR", rate_micro=900_000, as_of=datetime(2026, 3, 1))
            }
        )

        # Act: Buy 10 units at $100.00 with no fee
        result = wired.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.BUY,
                traded_on=date(2026, 3, 1),
                quantity_micro=10 * MICRO,
                price_micro=100 * 100 * MICRO,
                brokerage_account_id=broker_account.id,
            ),
        )

        # Assert: Verify $1000.00 was recorded as 900.00 euro
        assert result.cash_amount_minor == 90_000

    def test_it_must_be_a_brokerage_account(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that a trade cannot take cash out of a savings account.

        A brokerage balance is folded from its trades, so pointing one at a
        savings account would silently remove real savings that no transaction
        explains.
        """
        # Arrange: Offer a savings account instead
        savings = Account(
            household_id=HOUSEHOLD_ID,
            name="Piggy Savings",
            type=AccountType.SAVINGS,
            currency_code="EUR",
            opening_balance_minor=0,
            opening_balance_date=date(2025, 1, 1),
        )
        savings.id = uuid.UUID("99999999-9999-9999-9999-999999999999")
        wired.account_repository.get_for_household = MagicMock(return_value=savings)

        # Act & Assert: Verify it is refused by name
        with pytest.raises(NotABrokerageAccountError):
            wired.create_trade(
                household=household_context,
                trade_create=TradeCreate(
                    instrument_id=INSTRUMENT_ID,
                    side=TradeSide.BUY,
                    traded_on=date(2026, 3, 1),
                    quantity_micro=10 * MICRO,
                    price_micro=100 * 100 * MICRO,
                    brokerage_account_id=savings.id,
                ),
            )

    def test_an_account_from_another_household_is_not_found(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that a foreign account is a 404 rather than a 403.

        Saying an account exists but is not yours is saying something about
        another household.
        """
        # Arrange: Set up a repository that finds nothing
        wired.account_repository.get_for_household = MagicMock(return_value=None)

        # Act & Assert: Verify it is refused as missing
        with pytest.raises(AccountNotFoundError):
            wired.create_trade(
                household=household_context,
                trade_create=TradeCreate(
                    instrument_id=INSTRUMENT_ID,
                    side=TradeSide.BUY,
                    traded_on=date(2026, 3, 1),
                    quantity_micro=10 * MICRO,
                    price_micro=100 * 100 * MICRO,
                    brokerage_account_id=uuid.uuid4(),
                ),
            )

    def test_deleting_a_trade_removes_it_and_nothing_else(
        self, wired: InvestmentService, household_context: HouseholdContext, broker_account: Account
    ) -> None:
        """Test that removing a trade needs no ledger row unwound.

        A brokerage balance is folded from the trades themselves, so deleting
        the trade removes its effect. Nothing is left behind to strand.
        """
        # Arrange: Set up a trade with a cash side
        trade = make_trade(TradeSide.BUY, units=10, price_major=100)
        trade.brokerage_account_id = broker_account.id
        trade.cash_amount_minor = 100_000
        wired.trade_repository.get_for_household = MagicMock(return_value=trade)
        wired.trade_repository.history_for_instrument = MagicMock(return_value=[])
        wired.trade_repository.delete = MagicMock()

        # Act: Delete the trade
        wired.delete_trade(household=household_context, trade_id=trade.id)

        # Assert: Verify the trade went and nothing else was needed
        wired.trade_repository.delete.assert_called_once_with(trade)


class TestSameDayTrades:
    """Tests for two trades in one instrument on one day."""

    def test_a_second_trade_on_the_same_day_does_not_crash(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that a stored timestamp and a fresh one can be ordered together.

        Timestamps are stored without a zone, so a row read back is naive while
        one just built in Python carries UTC. They are only ever compared when
        two trades share a date, which is what buying and selling on one day
        does, and comparing them raises.
        """
        # Arrange: Set up a stored buy with a naive timestamp, as the database returns
        stored = make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 9, 5))
        stored.created_at = datetime(2026, 9, 5, 9, 0)
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.history_for_instrument = MagicMock(return_value=[stored])

        # Act: Sell on the same day, which builds a trade carrying UTC
        result = mock_investment_service.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.SELL,
                traded_on=date(2026, 9, 5),
                quantity_micro=4 * MICRO,
                price_micro=120 * 100 * MICRO,
            ),
        )

        # Assert: Verify it went through rather than raising on the comparison
        assert result.side == TradeSide.SELL

    def test_the_new_trade_still_sorts_after_the_stored_one(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
    ) -> None:
        """Test that ordering survives the timezone fix.

        If the fresh trade sorted first, a same-day sell would be replayed
        before the buy that supplied its units and be refused as an oversell.
        """
        # Arrange: Set up a buy stored earlier today, with only enough units
        stored = make_trade(TradeSide.BUY, units=4, price_major=100, traded_on=date(2026, 9, 5))
        stored.created_at = datetime(2026, 9, 5, 9, 0)
        instrument = make_instrument()
        mock_investment_service.instrument_repository.get_for_household = MagicMock(return_value=instrument)
        mock_investment_service.trade_repository.history_for_instrument = MagicMock(return_value=[stored])

        # Act: Sell exactly those units on the same day
        result = mock_investment_service.create_trade(
            household=household_context,
            trade_create=TradeCreate(
                instrument_id=INSTRUMENT_ID,
                side=TradeSide.SELL,
                traded_on=date(2026, 9, 5),
                quantity_micro=4 * MICRO,
                price_micro=120 * 100 * MICRO,
            ),
        )

        # Assert: Verify the sale was allowed, so the buy was replayed first
        assert result.quantity_micro == 4 * MICRO


class TestUnreachableRateProvider:
    """Tests for a rate provider that fails after the prices were fetched."""

    def test_it_keeps_the_prices_it_already_fetched(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that an unreachable rate provider does not throw away good quotes.

        Rates come from a different provider. Letting it raise would discard
        prices that were already paid for, and because nothing was stored the
        next press would spend those API calls all over again.
        """
        # Arrange: Set up a dollar holding whose price fetches but whose rate fails
        instrument = make_instrument(symbol="VOO.US", currency_code="USD")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})
        mock_price_provider.quotes.return_value = (
            {
                "VOO.US": Quote(
                    symbol="VOO.US",
                    price_micro=50_000 * MICRO,
                    currency_code="USD",
                    exchange="NYSEArca",
                    as_of=datetime(2026, 9, 5, 17, 30),
                )
            },
            {},
        )
        mock_price_provider.fx_rates.side_effect = PriceProviderError("it is rate limiting this address.")

        # Act: Refresh
        result = mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the price was kept and the rate failure was reported
        assert result.updated_count == 1
        assert instrument.last_price_micro == 50_000 * MICRO
        assert any("Exchange rates" in failure.symbol for failure in result.failures)
        mock_investment_service.session.commit.assert_called_once()

    def test_the_price_is_marked_as_fetched_so_it_is_not_paid_for_twice(
        self,
        mock_investment_service: InvestmentService,
        household_context: HouseholdContext,
        household: Household,
        mock_price_provider: MagicMock,
    ) -> None:
        """Test that a rate failure does not cost the quote budget a second time."""
        # Arrange: Set up the same failure
        instrument = make_instrument(symbol="VOO.US", currency_code="USD")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})
        mock_price_provider.quotes.return_value = (
            {
                "VOO.US": Quote(
                    symbol="VOO.US",
                    price_micro=50_000 * MICRO,
                    currency_code="USD",
                    exchange=None,
                    as_of=datetime(2026, 9, 5, 17, 30),
                )
            },
            {},
        )
        mock_price_provider.fx_rates.side_effect = PriceProviderError("it is rate limiting this address.")

        # Act: Refresh
        mock_investment_service.refresh_prices(household=household_context)

        # Assert: Verify the instrument counts as freshly priced
        assert instrument.last_priced_at is not None


class TestAPositionWithNoRate:
    """Tests for a holding whose currency has no exchange rate stored."""

    @pytest.fixture
    def wired(self, mock_investment_service: InvestmentService, household: Household) -> InvestmentService:
        """A dollar holding, priced, in a euro household with no dollar rate."""
        instrument = make_instrument(symbol="VOO.US", currency_code="USD", last_price_micro=50_000 * MICRO)
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[
                make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
                make_trade(TradeSide.SELL, units=4, price_major=150, traded_on=date(2026, 2, 1)),
            ]
        )
        return mock_investment_service

    def test_every_converted_figure_is_absent_rather_than_zero(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that a missing rate leaves no figure understated.

        Reporting a cost basis or a realised gain as zero because no rate is
        known understates by exactly the amount nobody can see, which is the
        opposite of what a missing market value already does.
        """
        # Act: Read the portfolio
        position = wired.get_portfolio(household=household_context).data[0]

        # Assert: Verify nothing was invented
        assert position.cost_basis_minor is None
        assert position.market_value_minor is None
        assert position.unrealised_gain_minor is None
        assert position.realised_gain_minor is None

    def test_it_is_counted_among_the_positions_that_could_not_be_valued(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that the page can say the total is partial."""
        # Act: Read the portfolio
        portfolio = wired.get_portfolio(household=household_context)

        # Assert: Verify it is counted
        assert portfolio.unpriced_count == 1


class TestASoldPositionWithNoRate:
    """Tests for the one case where the total can be silently short."""

    @pytest.fixture
    def wired(self, mock_investment_service: InvestmentService, household: Household) -> InvestmentService:
        """A dollar holding, sold in full, in a euro household with no dollar rate."""
        instrument = make_instrument(symbol="VOO.US", currency_code="USD")
        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(return_value=([instrument], 1))
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[
                make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
                make_trade(TradeSide.SELL, units=10, price_major=150, traded_on=date(2026, 2, 1)),
            ]
        )
        return mock_investment_service

    def test_it_is_still_counted_when_sold_positions_are_hidden(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that hiding the row does not also hide that a figure is missing.

        Its realised gain cannot be converted, so it adds nothing to the total.
        If it were not counted here either, the default view would understate
        and say nothing about it.
        """
        # Act: Read the portfolio the way the page does by default
        portfolio = wired.get_portfolio(household=household_context, include_closed=False)

        # Assert: Verify the row is hidden but the gap is still reported
        assert portfolio.data == []
        assert portfolio.unpriced_count == 1

    def test_the_count_is_the_same_either_way(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that the count follows the realised total rather than the listing."""
        # Act: Read it both ways
        hidden = wired.get_portfolio(household=household_context, include_closed=False)
        shown = wired.get_portfolio(household=household_context, include_closed=True)

        # Assert: Verify the toggle changes which rows are listed and nothing else
        assert hidden.unpriced_count == shown.unpriced_count == 1


class TestRealisedGainSurvivesTheFilter:
    """Tests that hiding sold positions does not hide the money they made."""

    @pytest.fixture
    def wired(self, mock_investment_service: InvestmentService, household: Household) -> InvestmentService:
        """A household holding one open position and one sold out completely."""
        open_one = make_instrument(symbol="VWCE.DE", last_price_micro=12_845 * MICRO)
        closed_one = make_instrument(symbol="SGLN.L")
        closed_one.id = uuid.UUID("44444444-4444-4444-4444-444444444444")

        mock_investment_service.household_repository.get_by_id = MagicMock(return_value=household)
        mock_investment_service.instrument_repository.list_for_household = MagicMock(
            return_value=([open_one, closed_one], 2)
        )
        mock_investment_service.fx_rate_repository.rates_into = MagicMock(return_value={})
        # The open one has never been sold; the closed one was bought and sold
        # in full, banking 100.00.
        mock_investment_service.trade_repository.history_for_household = MagicMock(
            return_value=[
                make_trade(TradeSide.BUY, units=10, price_major=100, traded_on=date(2026, 1, 1)),
                _trade_for(
                    closed_one.id,
                    make_trade(TradeSide.BUY, units=1, price_major=100, traded_on=date(2026, 1, 1)),
                ),
                _trade_for(
                    closed_one.id,
                    make_trade(TradeSide.SELL, units=1, price_major=200, traded_on=date(2026, 2, 1)),
                ),
            ]
        )
        return mock_investment_service

    def test_the_realised_total_is_the_same_either_way(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that hiding sold positions does not subtract from realised gains.

        A realised gain is a fact about the past: the money was banked. Turning
        on "show me more" must never make a total go down.
        """
        # Act: Read the portfolio with the sold position hidden, then shown
        hidden = wired.get_portfolio(household=household_context, include_closed=False)
        shown = wired.get_portfolio(household=household_context, include_closed=True)

        # Assert: Verify the money made is reported the same way twice
        assert hidden.total_realised_gain_minor == 10_000
        assert shown.total_realised_gain_minor == 10_000

    def test_the_filter_still_controls_which_rows_are_listed(
        self, wired: InvestmentService, household_context: HouseholdContext
    ) -> None:
        """Test that the toggle keeps doing its job of hiding the row itself."""
        # Act: Read the portfolio both ways
        hidden = wired.get_portfolio(household=household_context, include_closed=False)
        shown = wired.get_portfolio(household=household_context, include_closed=True)

        # Assert: Verify only the listing changed
        assert [position.symbol for position in hidden.data] == ["VWCE.DE"]
        assert [position.symbol for position in shown.data] == ["VWCE.DE", "SGLN.L"]
