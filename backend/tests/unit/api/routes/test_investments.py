import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db, get_household_context, get_investment_service
from app.exceptions import (
    InstrumentExistsError,
    InstrumentInUseError,
    InstrumentNotFoundError,
    InstrumentNotPriceableError,
    InsufficientUnitsError,
    PriceProviderError,
    PriceProviderNotConfiguredError,
    TradeNotFoundError,
)
from app.main import app
from app.models import (
    HouseholdContext,
    InstrumentKind,
    InstrumentPublic,
    InstrumentsPublic,
    Message,
    PortfolioPublic,
    PositionPublic,
    PriceRefreshResult,
    QuoteFailure,
    SymbolMatch,
    SymbolMatchesPublic,
    TradePublic,
    TradeSide,
    TradesPublic,
    User,
)
from app.models.fields import MICRO

HOUSEHOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
INSTRUMENT_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
TRADE_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


def make_instrument_public() -> InstrumentPublic:
    """Build an instrument response payload."""
    return InstrumentPublic(
        id=INSTRUMENT_ID,
        household_id=HOUSEHOLD_ID,
        symbol="VWCE.DE",
        name="Vanguard FTSE All-World",
        kind=InstrumentKind.ETF,
        currency_code="EUR",
        exchange="XETRA",
        last_price_micro=12_845 * MICRO,
        last_price_at=datetime(2026, 9, 4, 17, 30),
        created_at=datetime.now(UTC),
    )


def make_trade_public() -> TradePublic:
    """Build a trade response payload."""
    return TradePublic(
        id=TRADE_ID,
        household_id=HOUSEHOLD_ID,
        instrument_id=INSTRUMENT_ID,
        symbol="VWCE.DE",
        currency_code="EUR",
        side=TradeSide.BUY,
        traded_on=date(2026, 1, 15),
        quantity_micro=10 * MICRO,
        price_micro=10_000 * MICRO,
        fee_minor=0,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock investment service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_investment_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestCreateInstrument:
    """Tests for POST /investments/instruments."""

    def test_creates_an_instrument(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a service that tracks the instrument
        wire.create_instrument.return_value = make_instrument_public()

        # Act: Post an instrument with no currency, leaving it to the provider
        response = client.post(
            "/api/v1/investments/instruments",
            json={"symbol": "VWCE.DE", "name": "Vanguard FTSE All-World"},
        )

        # Assert: Verify it was created with the provider's currency
        assert response.status_code == 200
        assert response.json()["currency_code"] == "EUR"

    def test_a_duplicate_symbol_is_a_conflict(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a household that already tracks the symbol
        wire.create_instrument.side_effect = InstrumentExistsError(symbol="VWCE.DE")

        # Act: Post it again
        response = client.post("/api/v1/investments/instruments", json={"symbol": "VWCE.DE", "name": "Duplicate"})

        # Assert: Verify it is a 409
        assert response.status_code == 409

    def test_an_unpriceable_symbol_is_a_bad_request(self, client: TestClient, wire: MagicMock) -> None:
        """Test that a symbol nothing can price is the caller's to correct."""
        # Arrange: Set up a provider that does not know the symbol
        wire.create_instrument.side_effect = InstrumentNotPriceableError(symbol="TYPO.XX")

        # Act: Post it
        response = client.post("/api/v1/investments/instruments", json={"symbol": "TYPO.XX", "name": "A typo"})

        # Assert: Verify it is a 400 that explains both ways forward
        assert response.status_code == 400
        assert "set the currency yourself" in response.json()["detail"]

    def test_an_unreachable_provider_is_a_bad_gateway(self, client: TestClient, wire: MagicMock) -> None:
        """Test that an upstream failure is not reported as this app's fault."""
        # Arrange: Set up a provider that cannot be reached
        wire.create_instrument.side_effect = PriceProviderError("it timed out.")

        # Act: Post an instrument
        response = client.post("/api/v1/investments/instruments", json={"symbol": "VWCE.DE", "name": "Anything"})

        # Assert: Verify it is a 502, which says a retry is worth trying
        assert response.status_code == 502

    def test_market_data_switched_off_is_service_unavailable(self, client: TestClient, wire: MagicMock) -> None:
        """Test that a switched-off feature is distinguishable from a broken one."""
        # Arrange: Set up a deployment with no provider
        wire.create_instrument.side_effect = PriceProviderNotConfiguredError()

        # Act: Post an instrument
        response = client.post("/api/v1/investments/instruments", json={"symbol": "VWCE.DE", "name": "Anything"})

        # Assert: Verify it is a 503
        assert response.status_code == 503

    def test_a_symbol_that_is_too_long_is_rejected_before_the_service(
        self, client: TestClient, wire: MagicMock
    ) -> None:
        # Arrange & Act: Post a symbol past the column's length
        response = client.post("/api/v1/investments/instruments", json={"symbol": "X" * 33, "name": "Too long"})

        # Assert: Verify the schema refused it
        assert response.status_code == 422
        wire.create_instrument.assert_not_called()


class TestListInstruments:
    """Tests for GET /investments/instruments."""

    def test_lists_them(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up one tracked instrument
        wire.list_instruments.return_value = InstrumentsPublic(data=[make_instrument_public()], count=1)

        # Act: List them
        response = client.get("/api/v1/investments/instruments")

        # Assert: Verify the page came back
        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_caps_the_page_size(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange & Act: Ask for more than the endpoint allows
        response = client.get("/api/v1/investments/instruments", params={"limit": 500})

        # Assert: Verify the request was refused rather than served
        assert response.status_code == 422


class TestDeleteInstrument:
    """Tests for DELETE /investments/instruments/{instrument_id}."""

    def test_deletes_it(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a service that deletes it
        wire.delete_instrument.return_value = Message(message="Instrument deleted.")

        # Act: Delete it
        response = client.delete(f"/api/v1/investments/instruments/{INSTRUMENT_ID}")

        # Assert: Verify it was confirmed
        assert response.status_code == 200

    def test_one_with_trades_is_a_conflict(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up an instrument that still has history
        wire.delete_instrument.side_effect = InstrumentInUseError(symbol="VWCE.DE")

        # Act: Delete it
        response = client.delete(f"/api/v1/investments/instruments/{INSTRUMENT_ID}")

        # Assert: Verify it is a 409
        assert response.status_code == 409

    def test_one_from_another_household_is_not_found(self, client: TestClient, wire: MagicMock) -> None:
        """Test that another household's ID is a 404, never a 403.

        A 403 would confirm the ID exists, which is exactly what must not leak.
        """
        # Arrange: Set up a scoped lookup that finds nothing
        wire.delete_instrument.side_effect = InstrumentNotFoundError()

        # Act: Delete it
        response = client.delete(f"/api/v1/investments/instruments/{INSTRUMENT_ID}")

        # Assert: Verify it is a 404
        assert response.status_code == 404


class TestCreateTrade:
    """Tests for POST /investments/trades."""

    def test_records_a_buy(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a service that records it
        wire.create_trade.return_value = make_trade_public()

        # Act: Post the trade
        response = client.post(
            "/api/v1/investments/trades",
            json={
                "instrument_id": str(INSTRUMENT_ID),
                "side": "buy",
                "traded_on": "2026-01-15",
                "quantity_micro": 10 * MICRO,
                "price_micro": 10_000 * MICRO,
            },
        )

        # Assert: Verify it was recorded
        assert response.status_code == 200
        assert response.json()["side"] == "buy"

    def test_overselling_is_a_bad_request(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a sale of more units than are held
        wire.create_trade.side_effect = InsufficientUnitsError(symbol="VWCE.DE")

        # Act: Post the trade
        response = client.post(
            "/api/v1/investments/trades",
            json={
                "instrument_id": str(INSTRUMENT_ID),
                "side": "sell",
                "traded_on": "2026-01-15",
                "quantity_micro": 10 * MICRO,
                "price_micro": 10_000 * MICRO,
            },
        )

        # Assert: Verify it is a 400 that says what went wrong
        assert response.status_code == 400
        assert "more units" in response.json()["detail"]

    def test_a_quantity_of_zero_is_rejected(self, client: TestClient, wire: MagicMock) -> None:
        """Test that a trade of nothing never reaches the service."""
        # Arrange & Act: Post a trade with no units in it
        response = client.post(
            "/api/v1/investments/trades",
            json={
                "instrument_id": str(INSTRUMENT_ID),
                "side": "buy",
                "traded_on": "2026-01-15",
                "quantity_micro": 0,
                "price_micro": 10_000 * MICRO,
            },
        )

        # Assert: Verify the schema refused it
        assert response.status_code == 422
        wire.create_trade.assert_not_called()

    def test_a_negative_fee_is_rejected(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange & Act: Post a trade with a fee that pays the household
        response = client.post(
            "/api/v1/investments/trades",
            json={
                "instrument_id": str(INSTRUMENT_ID),
                "side": "buy",
                "traded_on": "2026-01-15",
                "quantity_micro": MICRO,
                "price_micro": MICRO,
                "fee_minor": -100,
            },
        )

        # Assert: Verify the schema refused it
        assert response.status_code == 422

    def test_an_absurd_quantity_is_rejected(self, client: TestClient, wire: MagicMock) -> None:
        """Test that a quantity past the column's range is a 422, not a 500."""
        # Arrange & Act: Post a quantity beyond what the cap allows
        response = client.post(
            "/api/v1/investments/trades",
            json={
                "instrument_id": str(INSTRUMENT_ID),
                "side": "buy",
                "traded_on": "2026-01-15",
                "quantity_micro": 10**30,
                "price_micro": MICRO,
            },
        )

        # Assert: Verify it was refused with a validation error
        assert response.status_code == 422


class TestDeleteTrade:
    """Tests for DELETE /investments/trades/{trade_id}."""

    def test_a_missing_trade_is_not_found(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a scoped lookup that finds nothing
        wire.delete_trade.side_effect = TradeNotFoundError()

        # Act: Delete it
        response = client.delete(f"/api/v1/investments/trades/{TRADE_ID}")

        # Assert: Verify it is a 404
        assert response.status_code == 404

    def test_removing_units_a_later_sale_needed_is_refused(self, client: TestClient, wire: MagicMock) -> None:
        """Test that deleting a buy cannot leave a later sale unsupported."""
        # Arrange: Set up a delete that would leave the position short
        wire.delete_trade.side_effect = InsufficientUnitsError(symbol="VWCE.DE")

        # Act: Delete it
        response = client.delete(f"/api/v1/investments/trades/{TRADE_ID}")

        # Assert: Verify it is a 400
        assert response.status_code == 400


class TestListTrades:
    """Tests for GET /investments/trades."""

    def test_lists_them(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up one recorded trade
        wire.list_trades.return_value = TradesPublic(data=[make_trade_public()], count=1)

        # Act: List them
        response = client.get("/api/v1/investments/trades")

        # Assert: Verify the page came back
        assert response.status_code == 200
        assert response.json()["data"][0]["symbol"] == "VWCE.DE"


class TestGetPortfolio:
    """Tests for GET /investments/portfolio."""

    def test_returns_the_positions_and_the_totals(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up one position worth more than it cost
        wire.get_portfolio.return_value = PortfolioPublic(
            currency_code="EUR",
            data=[
                PositionPublic(
                    instrument_id=INSTRUMENT_ID,
                    symbol="VWCE.DE",
                    name="Vanguard FTSE All-World",
                    kind=InstrumentKind.ETF,
                    currency_code="EUR",
                    quantity_micro=10 * MICRO,
                    cost_basis_minor=100_000,
                    market_value_minor=120_000,
                    unrealised_gain_minor=20_000,
                )
            ],
            count=1,
            total_cost_basis_minor=100_000,
            total_market_value_minor=120_000,
            total_unrealised_gain_minor=20_000,
        )

        # Act: Read the portfolio
        response = client.get("/api/v1/investments/portfolio")

        # Assert: Verify the totals came back in the household's currency
        assert response.status_code == 200
        body = response.json()
        assert body["currency_code"] == "EUR"
        assert body["total_market_value_minor"] == 120_000

    def test_never_waits_on_the_provider(self, client: TestClient, wire: MagicMock) -> None:
        """Test that reading the portfolio does not fetch prices.

        The page has to render while the provider is down or rate limiting, so
        it reads what was last stored and refreshing is a separate request.
        """
        # Arrange: Set up an empty portfolio
        wire.get_portfolio.return_value = PortfolioPublic(currency_code="EUR", data=[], count=0)

        # Act: Read the portfolio
        response = client.get("/api/v1/investments/portfolio")

        # Assert: Verify nothing was refreshed on the way
        assert response.status_code == 200
        wire.refresh_prices.assert_not_called()


class TestRefreshPrices:
    """Tests for POST /investments/prices/refresh."""

    def test_reports_what_it_updated(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a refresh that priced two of three holdings
        wire.refresh_prices.return_value = PriceRefreshResult(
            updated_count=2,
            failures=[QuoteFailure(symbol="GONE.XX", reason="No data found")],
            refreshed_at=datetime(2026, 9, 5, 9, 0),
        )

        # Act: Refresh
        response = client.post("/api/v1/investments/prices/refresh")

        # Assert: Verify both halves of the outcome are reported
        assert response.status_code == 200
        body = response.json()
        assert body["updated_count"] == 2
        assert body["failures"][0]["symbol"] == "GONE.XX"

    def test_an_unreachable_provider_is_a_bad_gateway(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up a provider that is rate limiting
        wire.refresh_prices.side_effect = PriceProviderError(
            "it is rate limiting this address. Wait a minute and try again."
        )

        # Act: Refresh
        response = client.post("/api/v1/investments/prices/refresh")

        # Assert: Verify it is a 502 that says what to do
        assert response.status_code == 502
        assert "Wait a minute" in response.json()["detail"]


class TestSearchSymbols:
    """Tests for GET /investments/symbols."""

    def test_returns_matches(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange: Set up one match
        wire.search_symbols.return_value = SymbolMatchesPublic(
            data=[
                SymbolMatch(
                    symbol="VWCE.DE",
                    name="Vanguard FTSE All-World UCITS ETF",
                    exchange="XETRA",
                    kind=InstrumentKind.ETF,
                )
            ],
            count=1,
        )

        # Act: Search
        response = client.get("/api/v1/investments/symbols", params={"q": "all-world"})

        # Assert: Verify the match came back without a currency, which the
        # search index does not carry
        assert response.status_code == 200
        assert response.json()["data"][0]["symbol"] == "VWCE.DE"
        assert response.json()["data"][0]["currency_code"] is None

    def test_an_empty_query_is_rejected(self, client: TestClient, wire: MagicMock) -> None:
        # Arrange & Act: Search for nothing
        response = client.get("/api/v1/investments/symbols", params={"q": ""})

        # Assert: Verify the request was refused rather than proxied
        assert response.status_code == 422
        wire.search_symbols.assert_not_called()
