import datetime
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.exceptions import PriceProviderError, PriceProviderNotConfiguredError
from app.models import InstrumentKind
from app.models.fields import MICRO
from app.services import prices
from app.services.prices import (
    EodhdProvider,
    FrankfurterFxProvider,
    NullPriceProvider,
    YahooFinanceProvider,
)


class FakeResponse:
    """An httpx-shaped response that answers from a canned body."""

    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else ""

    def json(self) -> Any:
        if isinstance(self.payload, str):
            raise ValueError("not JSON")
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]


class FakeClient:
    """A client that answers by matching the URL it is asked for."""

    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str] | None = None) -> FakeResponse:
        self.calls.append((url, params or {}))
        for fragment, response in self.routes.items():
            if fragment in url:
                return response
        return FakeResponse({}, status_code=404)


@pytest.fixture
def provider() -> YahooFinanceProvider:
    return YahooFinanceProvider(
        base_url="https://example.test",
        search_url="https://example.test/v1/finance/search",
        timeout_seconds=1.0,
        user_agent="tests",
    )


# What the `wire` fixture hands a test: install a route table, get the client
# that recorded the calls back.
Wire = Callable[[dict[str, "FakeResponse"]], "FakeClient"]


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    """Put a fake client behind the provider, and skip the token handshake."""

    def install(routes: dict[str, FakeResponse]) -> FakeClient:
        client = FakeClient(routes)
        monkeypatch.setattr(prices, "_client", lambda _provider: client)
        monkeypatch.setattr(prices, "_crumb", lambda _provider: "token")
        return client

    return install


def quote_body(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the body the batched quote endpoint answers with."""
    return {"quoteResponse": {"result": rows, "error": None}}


class TestQuotes:
    """Tests for fetching prices."""

    def test_reads_a_price_into_minor_units(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a decimal price lands as scaled minor units, exactly."""
        # Arrange: Set up a listing quoted at 128.4567 euro
        wire(
            {
                "/v7/finance/quote": FakeResponse(
                    quote_body(
                        [
                            {
                                "symbol": "VWCE.DE",
                                "currency": "EUR",
                                "regularMarketPrice": 128.4567,
                                "regularMarketTime": 1_788_000_000,
                                "fullExchangeName": "XETRA",
                            }
                        ]
                    )
                )
            }
        )

        # Act: Fetch the quote
        found, failed = provider.quotes(["VWCE.DE"])

        # Assert: Verify 128.4567 became 12845.67 cents, times MICRO
        assert failed == {}
        assert found["VWCE.DE"].price_micro == 12_845_670_000
        assert found["VWCE.DE"].currency_code == "EUR"
        assert found["VWCE.DE"].exchange == "XETRA"

    def test_a_zero_decimal_currency_keeps_its_whole_units(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that the yen is not given cents it has no minor unit for."""
        # Arrange: Set up a listing quoted at 3200 yen
        wire(
            {
                "/v7/finance/quote": FakeResponse(
                    quote_body([{"symbol": "7203.T", "currency": "JPY", "regularMarketPrice": 3200}])
                )
            }
        )

        # Act: Fetch the quote
        found, _ = provider.quotes(["7203.T"])

        # Assert: Verify the price is 3200 units rather than 320000 of anything
        assert found["7203.T"].price_micro == 3200 * MICRO

    def test_asks_for_every_symbol_in_one_request(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a portfolio costs one request rather than one per holding.

        This is what keeps the provider's rate limit from being tripped, so it
        is the behaviour worth pinning rather than an implementation detail.
        """
        # Arrange: Set up three listings, all answered
        rows = [{"symbol": symbol, "currency": "EUR", "regularMarketPrice": 10} for symbol in ("A.DE", "B.DE", "C.DE")]
        client = wire({"/v7/finance/quote": FakeResponse(quote_body(rows))})

        # Act: Fetch all three
        found, _ = provider.quotes(["A.DE", "B.DE", "C.DE"])

        # Assert: Verify one request carried all three symbols
        assert len(found) == 3
        assert len(client.calls) == 1
        assert client.calls[0][1]["symbols"] == "A.DE,B.DE,C.DE"

    def test_falls_back_per_symbol_for_what_the_batch_missed(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a symbol the batch skipped is retried against the other endpoint."""
        # Arrange: Set up a batch that answers for one of two symbols, and a
        # chart endpoint that knows the other
        client = wire(
            {
                "/v7/finance/quote": FakeResponse(
                    quote_body([{"symbol": "A.DE", "currency": "EUR", "regularMarketPrice": 10}])
                ),
                "/v8/finance/chart/": FakeResponse(
                    {
                        "chart": {
                            "result": [{"meta": {"currency": "EUR", "regularMarketPrice": 20, "symbol": "B.DE"}}],
                            "error": None,
                        }
                    }
                ),
            }
        )

        # Act: Fetch both
        found, failed = provider.quotes(["A.DE", "B.DE"])

        # Assert: Verify both were priced, the second by the fallback
        assert failed == {}
        assert found["B.DE"].price_micro == 2_000 * MICRO
        assert any("/v8/finance/chart/" in url for url, _ in client.calls)

    def test_an_unknown_symbol_is_reported_rather_than_raised(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that one delisted ticker does not stop the rest being priced."""
        # Arrange: Set up a batch that skips the symbol and a chart that denies it
        wire(
            {
                "/v7/finance/quote": FakeResponse(quote_body([])),
                "/v8/finance/chart/": FakeResponse(
                    {"chart": {"result": None, "error": {"description": "No data found"}}}
                ),
            }
        )

        # Act: Fetch it
        found, failed = provider.quotes(["GONE.XX"])

        # Assert: Verify it came back as a reason, not an exception
        assert found == {}
        assert failed["GONE.XX"] == "No data found"

    def test_rate_limiting_says_what_to_do_about_it(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a 429 is explained rather than surfacing as a bare status."""
        # Arrange: Set up a provider that is refusing this address
        wire(
            {
                "/v7/finance/quote": FakeResponse("Too Many Requests", status_code=429),
                "/v8/finance/chart/": FakeResponse("Too Many Requests", status_code=429),
            }
        )

        # Act & Assert: Verify nothing came back at all, so it is raised once
        # rather than repeated as a failure against every holding
        with pytest.raises(PriceProviderError) as exc_info:
            provider.quotes(["VWCE.DE"])

        assert "rate limiting" in str(exc_info.value)

    def test_a_rate_limited_retry_does_not_discard_what_the_batch_fetched(
        self, provider: YahooFinanceProvider, wire: Wire
    ) -> None:
        """Test that one refused retry keeps the prices already in hand.

        The batch answers for nine holdings and skips the tenth. Retrying that
        one is what trips the limit, and losing the nine over it would be a
        much worse outcome than reporting the one.
        """
        # Arrange: Set up a batch that answers for one symbol but not the other,
        # and a fallback endpoint that is refusing this address
        wire(
            {
                "/v7/finance/quote": FakeResponse(
                    quote_body([{"symbol": "A.DE", "currency": "EUR", "regularMarketPrice": 10}])
                ),
                "/v8/finance/chart/": FakeResponse("Too Many Requests", status_code=429),
            }
        )

        # Act: Fetch both
        found, failed = provider.quotes(["A.DE", "B.DE"])

        # Assert: Verify the first survived and only the second is reported
        assert found["A.DE"].price_micro == 1_000 * MICRO
        assert "rate limiting" in failed["B.DE"]

    def test_a_row_with_no_price_is_not_treated_as_free(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a missing price is a failure rather than a price of zero."""
        # Arrange: Set up a row the provider returned without a price
        wire(
            {
                "/v7/finance/quote": FakeResponse(quote_body([{"symbol": "A.DE", "currency": "EUR"}])),
                "/v8/finance/chart/": FakeResponse({"chart": {"result": None, "error": {}}}),
            }
        )

        # Act: Fetch it
        found, failed = provider.quotes(["A.DE"])

        # Assert: Verify it failed rather than arriving as nothing
        assert found == {}
        assert "A.DE" in failed


class TestFxRates:
    """Tests for fetching exchange rates."""

    def test_reads_a_rate_for_a_pair(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a pair is priced as an instrument and read back as a rate."""
        # Arrange: Set up the dollar priced at 0.92 euro
        client = wire(
            {
                "/v7/finance/quote": FakeResponse(
                    quote_body([{"symbol": "USDEUR=X", "currency": "EUR", "regularMarketPrice": 0.92}])
                )
            }
        )

        # Act: Fetch the rate
        found, failed = provider.fx_rates([("USD", "EUR")])

        # Assert: Verify the rate came back as a plain number, not as cents
        assert failed == {}
        assert found[("USD", "EUR")].rate_micro == 920_000
        assert client.calls[0][1]["symbols"] == "USDEUR=X"

    def test_a_pair_that_failed_is_named_as_a_pair(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a failure reads as "USD/EUR" rather than as a ticker."""
        # Arrange: Set up a provider that knows nothing about the pair
        wire(
            {
                "/v7/finance/quote": FakeResponse(quote_body([])),
                "/v8/finance/chart/": FakeResponse(
                    {"chart": {"result": None, "error": {"description": "No data found"}}}
                ),
            }
        )

        # Act: Fetch the rate
        found, failed = provider.fx_rates([("USD", "EUR")])

        # Assert: Verify the failure is reported against the pair
        assert found == {}
        assert "USD/EUR" in failed


class TestSearch:
    """Tests for looking up listings."""

    def test_maps_a_match(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        # Arrange: Set up one result from the search index
        wire(
            {
                "/v1/finance/search": FakeResponse(
                    {
                        "quotes": [
                            {
                                "symbol": "VWCE.DE",
                                "longname": "Vanguard FTSE All-World UCITS ETF",
                                "exchDisp": "XETRA",
                                "quoteType": "ETF",
                                "isYahooFinance": True,
                            }
                        ]
                    }
                )
            }
        )

        # Act: Search for it
        matches = provider.search("all-world", limit=10)

        # Assert: Verify it mapped, with no currency, which the index does not carry
        assert len(matches) == 1
        assert matches[0].symbol == "VWCE.DE"
        assert matches[0].kind == InstrumentKind.ETF
        assert matches[0].currency_code is None

    def test_drops_a_row_the_provider_does_not_own(self, provider: YahooFinanceProvider, wire: Wire) -> None:
        """Test that a match nothing could then price is never offered."""
        # Arrange: Set up a result the provider says is not its own
        wire(
            {
                "/v1/finance/search": FakeResponse(
                    {"quotes": [{"symbol": "X", "shortname": "X", "isYahooFinance": False}]}
                )
            }
        )

        # Act: Search for it
        matches = provider.search("x", limit=10)

        # Assert: Verify it was left out
        assert matches == []

    def test_an_unexpected_body_is_no_matches_rather_than_a_crash(
        self, provider: YahooFinanceProvider, wire: Wire
    ) -> None:
        # Arrange: Set up a body with nothing recognisable in it
        wire({"/v1/finance/search": FakeResponse({"unexpected": True})})

        # Act: Search
        matches = provider.search("x", limit=10)

        # Assert: Verify it degraded to no matches
        assert matches == []


class TestNullPriceProvider:
    """Tests for the provider used when market data is switched off."""

    def test_reports_that_it_is_not_configured(self) -> None:
        # Arrange & Act & Assert: Verify it says so rather than pretending
        assert NullPriceProvider().is_configured is False

    def test_refuses_rather_than_returning_nothing(self) -> None:
        """Test that it raises, so a portfolio is never valued at zero by accident."""
        # Arrange: Set up the null provider
        provider = NullPriceProvider()

        # Act & Assert: Verify every call is refused
        with pytest.raises(PriceProviderNotConfiguredError):
            provider.quotes(["VWCE.DE"])
        with pytest.raises(PriceProviderNotConfiguredError):
            provider.fx_rates([("USD", "EUR")])
        with pytest.raises(PriceProviderNotConfiguredError):
            provider.search("x", limit=5)


class TestTimestamp:
    """Tests for reading when a quote was current."""

    def test_reads_a_unix_timestamp(self) -> None:
        # Arrange & Act: Read a real timestamp
        moment = prices._timestamp(1_788_000_000)

        # Assert: Verify it became the moment it stands for
        assert moment == datetime.datetime.fromtimestamp(1_788_000_000, tz=datetime.UTC)

    def test_a_missing_timestamp_becomes_now(self) -> None:
        """Test that no timestamp does not make a fresh price look ancient."""
        # Arrange: Note the time before the call
        before = datetime.datetime.now(datetime.UTC)

        # Act: Read a missing timestamp
        moment = prices._timestamp(None)

        # Assert: Verify it landed on now rather than on the epoch
        assert moment >= before


class TestCrumbHandshake:
    """Tests for the token a batched request has to carry."""

    def test_a_refused_handshake_is_explained(
        self, provider: YahooFinanceProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a rate limited handshake says so rather than failing opaquely."""
        # Arrange: Set up a provider refusing the handshake, and no cached token
        monkeypatch.setattr(prices, "_client", lambda _p: FakeClient({"": FakeResponse("no", status_code=429)}))
        prices._forget_crumb()

        # Act & Assert: Verify the failure names the rate limit
        with pytest.raises(PriceProviderError) as exc_info:
            prices._crumb(provider)

        assert "rate limiting" in str(exc_info.value)


class TestFrankfurterFxProvider:
    """Tests for the exchange rate provider."""

    @pytest.fixture
    def fx(self) -> FrankfurterFxProvider:
        return FrankfurterFxProvider(base_url="https://rates.test/v1", timeout_seconds=1.0)

    def test_one_request_covers_every_pair_out_of_a_base(
        self, fx: FrankfurterFxProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that pairs sharing a base currency cost one request, not three."""
        # Arrange: Record every request and answer with three rates out of USD
        calls: list[tuple[str, dict[str, str]]] = []

        def fake(url: str, params: dict[str, str], **_kwargs: Any) -> Any:
            calls.append((url, params))
            return {"base": "USD", "date": "2026-09-04", "rates": {"EUR": 0.86044, "GBP": 0.74, "CHF": 0.8}}

        monkeypatch.setattr(prices, "_fetch_json", fake)

        # Act: Ask for three pairs that all convert out of dollars
        found, failed = fx.fx_rates([("USD", "EUR"), ("USD", "GBP"), ("USD", "CHF")])

        # Assert: Verify one request answered all three
        assert len(calls) == 1
        assert failed == {}
        assert found[("USD", "EUR")].rate_micro == 860_440
        assert found[("USD", "GBP")].rate_micro == 740_000

    def test_a_pair_the_bank_does_not_publish_is_reported_not_guessed(
        self, fx: FrankfurterFxProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a missing rate becomes a named failure rather than a default."""
        # Arrange: Answer with a response that omits the currency asked for
        monkeypatch.setattr(
            prices,
            "_fetch_json",
            lambda url, params, timeout_seconds, redact=None: {"date": "2026-09-04", "rates": {}},
        )

        # Act: Ask for a pair the response does not carry
        found, failed = fx.fx_rates([("USD", "XYZ")])

        # Assert: Verify nothing was invented and the pair is named
        assert found == {}
        assert "USD/XYZ" in failed

    def test_the_rate_is_dated_the_day_the_bank_published_it(
        self, fx: FrankfurterFxProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the published date is kept rather than replaced with now."""
        # Arrange: Answer with a rate published on a known day
        monkeypatch.setattr(
            prices,
            "_fetch_json",
            lambda url, params, timeout_seconds, redact=None: {"date": "2026-09-04", "rates": {"EUR": 0.9}},
        )

        # Act: Fetch the pair
        found, _ = fx.fx_rates([("USD", "EUR")])

        # Assert: Verify the date came from the response
        assert found[("USD", "EUR")].as_of == datetime.datetime(2026, 9, 4, 0, 0, tzinfo=datetime.UTC)


class TestEodhdProvider:
    """Tests for the keyed price provider."""

    @pytest.fixture
    def eodhd(self) -> EodhdProvider:
        return EodhdProvider(
            api_key="secret-key",
            base_url="https://eod.test/api",
            timeout_seconds=1.0,
            fx_provider=FrankfurterFxProvider(base_url="https://rates.test/v1", timeout_seconds=1.0),
        )

    def test_no_api_key_means_the_provider_is_not_configured(self) -> None:
        """Test that an empty key reports as unconfigured rather than failing later."""
        # Arrange: Build a provider with no key
        provider = EodhdProvider(
            api_key="",
            base_url="https://eod.test/api",
            timeout_seconds=1.0,
            fx_provider=FrankfurterFxProvider(base_url="https://rates.test/v1", timeout_seconds=1.0),
        )

        # Act & Assert: Verify it says so
        assert provider.is_configured is False

    def test_every_symbol_goes_into_one_request(self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a batch is one HTTP request, with the rest of the symbols in a parameter."""
        # Arrange: Answer a batched request with a row per symbol
        calls: list[tuple[str, dict[str, str]]] = []

        def fake(url: str, params: dict[str, str], **_kwargs: Any) -> Any:
            calls.append((url, params))
            return [
                {"code": "VUAA.XETRA", "close": 105.5, "timestamp": 1788553740},
                {"code": "VOO.US", "close": 500.0, "timestamp": 1788553740},
            ]

        monkeypatch.setattr(prices, "_fetch_json", fake)

        # Act: Price two symbols whose currencies are known
        found, failed = eodhd.quotes(["VUAA.XETRA", "VOO.US"], currencies={"VUAA.XETRA": "EUR", "VOO.US": "USD"})

        # Assert: Verify one request carried both, and both were priced in minor units
        assert len(calls) == 1
        assert calls[0][1]["s"] == "VOO.US"
        assert failed == {}
        assert found["VUAA.XETRA"].price_micro == 10_550 * MICRO
        assert found["VOO.US"].price_micro == 50_000 * MICRO

    def test_a_single_symbol_response_is_an_object_not_an_array(
        self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the one-symbol response shape is read as well as the many-symbol one."""
        # Arrange: Answer with a bare object, which is what one symbol returns
        monkeypatch.setattr(
            prices,
            "_fetch_json",
            lambda url, params, timeout_seconds, redact=None: {
                "code": "VOO.US",
                "close": 500.0,
                "timestamp": 1788553740,
            },
        )

        # Act: Price the one symbol
        found, _ = eodhd.quotes(["VOO.US"], currencies={"VOO.US": "USD"})

        # Assert: Verify it was read
        assert found["VOO.US"].price_micro == 50_000 * MICRO

    def test_a_symbol_with_no_known_currency_is_refused_rather_than_assumed(
        self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that an unknown currency is a failure, because a price cannot be scaled without it.

        The response carries no currency, so guessing one would silently
        misprice a yen listing by a factor of a hundred.
        """
        # Arrange: Record whether the provider is called at all
        calls: list[str] = []

        def fake(url: str, _params: dict[str, str], **_kwargs: Any) -> Any:
            calls.append(url)
            return []

        monkeypatch.setattr(prices, "_fetch_json", fake)

        # Act: Price a symbol without saying what it quotes in
        found, failed = eodhd.quotes(["VOO.US"], currencies={})

        # Assert: Verify nothing was fetched and the symbol is named
        assert calls == []
        assert found == {}
        assert "currency" in failed["VOO.US"]

    def test_the_price_falls_back_to_the_previous_close(
        self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a session with no trade yet is still priced."""
        # Arrange: Answer the way the API does before the first trade of a day
        monkeypatch.setattr(
            prices,
            "_fetch_json",
            lambda url, params, timeout_seconds, redact=None: [
                {"code": "VOO.US", "close": "NA", "previousClose": 499.0, "timestamp": 1788553740}
            ],
        )

        # Act: Price it
        found, _ = eodhd.quotes(["VOO.US"], currencies={"VOO.US": "USD"})

        # Assert: Verify the previous close stood in
        assert found["VOO.US"].price_micro == 49_900 * MICRO

    def test_the_quote_never_claims_to_know_the_currency(
        self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that the quote reports no currency, since the response carries none.

        Echoing back what the caller supplied would let the app's own stored
        guess look like the provider confirming it.
        """
        # Arrange: Answer with a normal row
        monkeypatch.setattr(
            prices,
            "_fetch_json",
            lambda url, params, timeout_seconds, redact=None: [
                {"code": "VOO.US", "close": 500.0, "timestamp": 1788553740}
            ],
        )

        # Act: Price it
        found, _ = eodhd.quotes(["VOO.US"], currencies={"VOO.US": "USD"})

        # Assert: Verify the quote stays silent about currency
        assert found["VOO.US"].currency_code is None

    def test_search_joins_the_code_and_exchange_into_a_usable_symbol(
        self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that a match carries the symbol the quote endpoint answers to, and its currency."""
        # Arrange: Answer with the shape the search endpoint returns
        monkeypatch.setattr(
            prices,
            "_fetch_json",
            lambda url, params, timeout_seconds, redact=None: [
                {
                    "Code": "VUAA",
                    "Exchange": "XETRA",
                    "Name": "Vanguard S&P 500 UCITS ETF",
                    "Type": "ETF",
                    "Currency": "EUR",
                }
            ],
        )

        # Act: Search for it
        matches = eodhd.search("vuaa", limit=10)

        # Assert: Verify the symbol is the priceable one and the currency came through
        assert matches[0].symbol == "VUAA.XETRA"
        assert matches[0].currency_code == "EUR"
        assert matches[0].kind == InstrumentKind.ETF

    def test_exchange_rates_do_not_touch_the_metered_provider(
        self, eodhd: EodhdProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that rates go to the unmetered source, so they never spend the quote budget."""
        # Arrange: Record which host is asked
        hosts: list[str] = []

        def fake(url: str, _params: dict[str, str], **_kwargs: Any) -> Any:
            hosts.append(url)
            return {"date": "2026-09-04", "rates": {"EUR": 0.9}}

        monkeypatch.setattr(prices, "_fetch_json", fake)

        # Act: Ask for a rate
        found, _ = eodhd.fx_rates([("USD", "EUR")])

        # Assert: Verify the rate host answered and the price host was untouched
        assert all("eod.test" not in host for host in hosts)
        assert found[("USD", "EUR")].rate_micro == 900_000


class TestFetchJson:
    """Tests for the shared request helper."""

    def test_the_api_key_never_reaches_the_error_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a redacted parameter cannot leak through the library's own wording.

        The message ends up in an API response, and the failure text an HTTP
        library writes quotes the URL it was about, token and all.
        """

        # Arrange: Make the request fail the way a network error does
        class Boom:
            def __enter__(self) -> "Boom":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def get(self, url: str, params: dict[str, str] | None = None) -> FakeResponse:
                raise httpx.ConnectError(f"failed connecting to {url}?api_token=secret-key")

        monkeypatch.setattr(httpx, "Client", lambda **kwargs: Boom())

        # Act: Make a request whose token is redacted
        with pytest.raises(PriceProviderError) as caught:
            prices._fetch_json(
                "https://eod.test/api/real-time/VOO.US",
                {"api_token": "secret-key"},
                timeout_seconds=1.0,
                redact={"api_token"},
            )

        # Assert: Verify the secret is absent from what a caller would be shown
        assert "secret-key" not in str(caught.value)

    def test_a_refused_key_says_so_rather_than_reporting_a_bare_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that a 401 is explained as a key problem."""

        # Arrange: Answer every request with an unauthorized status
        class Refusing:
            def __enter__(self) -> "Refusing":
                return self

            def __exit__(self, *args: Any) -> None:
                return None

            def get(self, url: str, params: dict[str, str] | None = None) -> FakeResponse:
                return FakeResponse({}, status_code=401)

        monkeypatch.setattr(httpx, "Client", lambda **kwargs: Refusing())

        # Act: Make the request
        with pytest.raises(PriceProviderError) as caught:
            prices._fetch_json("https://eod.test/api", {"api_token": "k"}, 1.0, redact={"api_token"})

        # Assert: Verify the message points at the key
        assert "API key" in str(caught.value)


class TestNotConfiguredMessage:
    """Tests for what the app tells someone whose provider is switched off."""

    def test_it_names_a_setting_that_exists(self) -> None:
        """Test that the message points at a real setting rather than an old vendor.

        This message once named a provider the app had already moved off, which
        sent someone to set an environment variable nothing reads.
        """
        # Arrange: Read the settings the app actually understands
        from app.core.config import Settings

        # Act: Take the message a switched-off provider produces
        with pytest.raises(PriceProviderNotConfiguredError) as caught:
            NullPriceProvider().quotes(["VOO.US"])

        message = str(caught.value)

        # Assert: Verify every setting it names is one the app reads
        named = {word.strip(".,") for word in message.split() if word.strip(".,").isupper() and "_" in word}
        assert named
        assert named <= set(Settings.model_fields)
