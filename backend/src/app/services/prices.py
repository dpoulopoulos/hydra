"""Market data: what one unit of an instrument is worth right now.

Everything the rest of the app needs from the outside world sits behind
:class:`PriceProvider`. That boundary exists because a quote source is the one
part of this feature with no settled answer: the free keyed ones put European
listings behind a paid plan, the unkeyed ones are unofficial, and which is
right depends on where someone's money is. Swapping provider is then one class
and one setting rather than a rewrite of the portfolio.

Prices and rates are parsed with Decimal rather than float, so a price that is
exact on the wire is exact in the database too.
"""

import datetime
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote as urlquote

import httpx

from app.exceptions import PriceProviderError, PriceProviderNotConfiguredError
from app.models import InstrumentKind, SymbolMatch
from app.models.fields import MAX_FX_RATE_MICRO, MAX_PRICE_MICRO, MICRO, minor_digits

# What the provider calls an instrument, mapped to what this app calls one.
# Anything unrecognised becomes OTHER rather than a guess: the kind is a label
# for the person reading the page, so being vague beats being wrong.
_INSTRUMENT_KINDS = {
    "etf": InstrumentKind.ETF,
    "equity": InstrumentKind.STOCK,
    "mutualfund": InstrumentKind.FUND,
    "cryptocurrency": InstrumentKind.CRYPTO,
}


@dataclass(frozen=True)
class Quote:
    """The price of one unit of an instrument."""

    symbol: str
    # In minor units of `currency_code`, times MICRO.
    price_micro: int
    # What the provider says the listing quotes in. None when it did not say,
    # in which case the caller keeps whatever the instrument already recorded.
    currency_code: str | None
    exchange: str | None
    as_of: datetime.datetime


@dataclass(frozen=True)
class FxQuote:
    """The rate converting one currency into another."""

    base_code: str
    quote_code: str
    # How many units of the quote currency one unit of the base buys, times MICRO.
    rate_micro: int
    as_of: datetime.datetime


class PriceProvider(Protocol):
    """A source of market prices and exchange rates.

    The fetching methods return what they managed to get alongside the symbols
    they could not, rather than raising on the first bad one. A portfolio
    usually holds one delisted or mistyped ticker, and that must not stop the
    other nine from being valued. Being unable to reach the provider at all is
    different, and does raise.
    """

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called."""
        ...

    def quotes(
        self,
        symbols: Sequence[str],
        currencies: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Quote], dict[str, str]]:
        """Fetch the current price of several instruments.

        Args:
            symbols: The ticker symbols to price.
            currencies: What each symbol is already known to quote in. Some
                providers report the currency with the price and ignore this;
                others never report it, and cannot scale a price into minor
                units without being told. Callers pass what they have.

        Returns:
            Tuple of (quotes by symbol, reason by symbol for those that failed).
        """
        ...

    def fx_rates(self, pairs: Sequence[tuple[str, str]]) -> tuple[dict[tuple[str, str], FxQuote], dict[str, str]]:
        """Fetch the rate for several currency pairs.

        Args:
            pairs: (base, quote) currency code pairs.

        Returns:
            Tuple of (rates by pair, reason by pair name for those that failed).
        """
        ...

    def search(self, query: str, limit: int) -> list[SymbolMatch]:
        """Look up listings matching a name or partial ticker.

        Args:
            query: What the user typed.
            limit: The most matches to return.

        Returns:
            The matching listings.
        """
        ...


class NullPriceProvider:
    """The provider used when market data is switched off.

    It refuses rather than returning nothing, so the app never shows a
    portfolio worth zero and calls that an answer.
    """

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called.

        Returns:
            False, always.
        """
        return False

    def quotes(
        self,
        symbols: Sequence[str],
        currencies: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Quote], dict[str, str]]:
        """Refuse to fetch prices.

        Args:
            symbols: Ignored.
            currencies: Ignored.

        Raises:
            PriceProviderNotConfiguredError: Always.
        """
        raise PriceProviderNotConfiguredError from None

    def fx_rates(self, pairs: Sequence[tuple[str, str]]) -> tuple[dict[tuple[str, str], FxQuote], dict[str, str]]:
        """Refuse to fetch exchange rates.

        Args:
            pairs: Ignored.

        Raises:
            PriceProviderNotConfiguredError: Always.
        """
        raise PriceProviderNotConfiguredError from None

    def search(self, query: str, limit: int) -> list[SymbolMatch]:
        """Refuse to search for listings.

        Args:
            query: Ignored.
            limit: Ignored.

        Raises:
            PriceProviderNotConfiguredError: Always.
        """
        raise PriceProviderNotConfiguredError from None


class FrankfurterFxProvider:
    """Exchange rates from Frankfurter, which publishes the ECB's daily rates.

    Rates live here rather than on whoever supplies prices because the price
    provider is metered and this is not. Frankfurter needs no key, and one
    request returns every rate out of a single base currency, so a portfolio
    holding three foreign currencies costs three requests at most and usually
    one. That leaves the whole quote budget for quotes.

    The rates are the ECB reference set, published once each working day. They
    are the right answer for restating a portfolio and the wrong one for timing
    a trade, which is not what this app is for.
    """

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        """Initialize the Frankfurter rate provider.

        Args:
            base_url: The root of the API, without a trailing slash.
            timeout_seconds: How long to wait for one request.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def fx_rates(self, pairs: Sequence[tuple[str, str]]) -> tuple[dict[tuple[str, str], FxQuote], dict[str, str]]:
        """Fetch the rate for several currency pairs.

        Args:
            pairs: (base, quote) currency code pairs.

        Returns:
            Tuple of (rates by pair, reason by pair name for those that failed).

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        found: dict[tuple[str, str], FxQuote] = {}
        failed: dict[str, str] = {}

        # Grouped by base currency, because that is what one request covers.
        wanted: dict[str, list[str]] = {}
        for base_code, quote_code in pairs:
            wanted.setdefault(base_code.upper(), []).append(quote_code.upper())

        for base_code, quote_codes in wanted.items():
            payload = _fetch_json(
                f"{self.base_url}/latest",
                {"base": base_code, "symbols": ",".join(sorted(set(quote_codes)))},
                timeout_seconds=self.timeout_seconds,
            )

            rates = payload.get("rates") if isinstance(payload, dict) else None
            as_of = _date_or_now(payload.get("date") if isinstance(payload, dict) else None)

            for quote_code in quote_codes:
                rate = _decimal((rates or {}).get(quote_code)) if isinstance(rates, dict) else None
                rate_micro = _scaled(rate, MICRO) if rate is not None else 0

                if rate is None:
                    failed[f"{base_code}/{quote_code}"] = "The rate provider does not publish this currency pair."
                elif 0 < rate_micro <= MAX_FX_RATE_MICRO:
                    found[(base_code, quote_code)] = FxQuote(
                        base_code=base_code,
                        quote_code=quote_code,
                        rate_micro=rate_micro,
                        as_of=as_of,
                    )
                else:
                    failed[f"{base_code}/{quote_code}"] = "The rate provider returned a rate outside the stored range."

        return found, failed


class EodhdProvider:
    """Market data from EODHD, using an API key.

    Chosen because it is the one free plan checked that actually quotes
    European listings; the unkeyed sources are unofficial and rate limit an
    address within a handful of requests, and the other keyed free tiers either
    exclude those listings or charge for them.

    What matters about this provider is how it counts. A free plan allows
    twenty API calls a day, and a call is one *ticker*, not one request:
    batching five symbols into one HTTP request still spends five calls. So a
    five-holding portfolio can be refreshed four times a day and no more. The
    service layer is what keeps that budget, by reusing a stored price until it
    is older than the configured window and only asking about the rest.

    Two more things follow from the shape of the API. Its quote response says
    nothing about currency, so the currency of a listing is read from the
    search endpoint when the instrument is first tracked and taken from the
    stored row after that. And exchange rates are not fetched from here at all:
    they come from an unmetered provider, so that rates never compete with
    prices for the same twenty calls.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        fx_provider: "FrankfurterFxProvider",
        batch_size: int = 100,
    ) -> None:
        """Initialize the EODHD provider.

        Args:
            api_key: The API token. An empty one means the provider is off.
            base_url: The root of the API, without a trailing slash.
            timeout_seconds: How long to wait for one request.
            fx_provider: Where exchange rates come from.
            batch_size: The most symbols to put in one HTTP request. This
                bounds URL length, not spend: the cost is per symbol either way.
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.fx_provider = fx_provider
        self.batch_size = max(1, batch_size)

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called.

        Returns:
            True when an API key is set.
        """
        return bool(self.api_key)

    def quotes(
        self,
        symbols: Sequence[str],
        currencies: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Quote], dict[str, str]]:
        """Fetch the current price of several instruments.

        Args:
            symbols: The ticker symbols to price.
            currencies: What each symbol is known to quote in. Required here,
                because the response does not say and a price cannot be scaled
                into minor units without it. A symbol with no known currency is
                reported as failed rather than guessed at.

        Returns:
            Tuple of (quotes by symbol, reason by symbol for those that failed).

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        known = {symbol.upper(): code for symbol, code in (currencies or {}).items()}
        found: dict[str, Quote] = {}
        failed: dict[str, str] = {}

        askable = []
        for symbol in symbols:
            if symbol.upper() in known:
                askable.append(symbol)
            else:
                failed[symbol] = "This app does not know what currency the symbol quotes in."

        for start in range(0, len(askable), self.batch_size):
            batch = list(askable[start : start + self.batch_size])
            rows = self._live(batch)

            for symbol in batch:
                row = rows.get(symbol.upper())
                if row is None:
                    failed[symbol] = "The provider returned nothing for this symbol."
                    continue

                quote = self._to_quote(symbol, row, known[symbol.upper()])
                if isinstance(quote, Quote):
                    found[symbol] = quote
                else:
                    failed[symbol] = quote

        return found, failed

    def fx_rates(self, pairs: Sequence[tuple[str, str]]) -> tuple[dict[tuple[str, str], FxQuote], dict[str, str]]:
        """Fetch the rate for several currency pairs.

        Handed straight to the unmetered rate provider. EODHD does quote
        currency pairs, but each one would cost an API call out of the same
        daily budget as the prices, which is the scarce thing here.

        Args:
            pairs: (base, quote) currency code pairs.

        Returns:
            Tuple of (rates by pair, reason by pair name for those that failed).

        Raises:
            PriceProviderError: If the rate provider cannot be reached at all.
        """
        return self.fx_provider.fx_rates(pairs)

    def search(self, query: str, limit: int) -> list[SymbolMatch]:
        """Look up listings matching a name, ticker or ISIN.

        This is also how a listing's currency is discovered, since the quote
        endpoint never reports one.

        Args:
            query: What the user typed.
            limit: The most matches to return.

        Returns:
            The matching listings.

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        payload = self._get(f"{self.base_url}/search/{urlquote(query.strip(), safe='')}", {"limit": str(limit)})

        if not isinstance(payload, list):
            return []

        matches: list[SymbolMatch] = []
        for row in payload[:limit]:
            if not isinstance(row, dict):
                continue

            code = str(row.get("Code") or "").strip()
            exchange = str(row.get("Exchange") or "").strip()
            currency = str(row.get("Currency") or "").strip().upper()

            # The symbol this app stores is the one the quote endpoint answers
            # to, which is code and exchange joined. Offering a bare code would
            # produce a row that can never be priced.
            symbol = f"{code}.{exchange}" if code and exchange else code
            if not symbol or len(symbol) > 32:
                continue

            matches.append(
                SymbolMatch(
                    symbol=symbol.upper(),
                    name=str(row.get("Name") or symbol)[:255],
                    currency_code=currency if len(currency) == 3 else None,
                    exchange=exchange[:64] or None,
                    kind=_INSTRUMENT_KINDS.get(str(row.get("Type") or "").lower(), InstrumentKind.OTHER),
                )
            )

        return matches

    def _live(self, batch: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Fetch one request's worth of live quotes.

        The API puts the first symbol in the path and the rest in a parameter,
        and answers with a bare object for one symbol and an array for more.

        Args:
            batch: The symbols to ask about.

        Returns:
            The rows, keyed by the symbol they describe in upper case. A batch
            the provider could not answer yields an empty mapping rather than
            raising, so the caller reports each symbol as unanswered.

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        head, *rest = batch
        params = {"fmt": "json"}
        if rest:
            params["s"] = ",".join(rest)

        payload = self._get(f"{self.base_url}/real-time/{urlquote(head, safe='.-^=')}", params)
        rows = payload if isinstance(payload, list) else [payload]

        return {str(row.get("code") or "").upper(): row for row in rows if isinstance(row, dict) and row.get("code")}

    def _get(self, url: str, params: dict[str, str]) -> Any:
        """Make one request to the provider.

        Args:
            url: The full URL to request.
            params: Query parameters. The API token is added here so no caller
                has to remember it, and so it never appears in a log line
                written by one.

        Returns:
            The decoded JSON body.

        Raises:
            PriceProviderError: If the request fails or the body is not JSON.
        """
        return _fetch_json(
            url,
            {**params, "api_token": self.api_key},
            timeout_seconds=self.timeout_seconds,
            redact={"api_token"},
        )

    def _to_quote(self, symbol: str, row: dict[str, Any], currency_code: str) -> Quote | str:
        """Parse one symbol's block into a quote.

        Args:
            symbol: The symbol the block belongs to.
            row: The block from the response.
            currency_code: What the symbol is known to quote in.

        Returns:
            The quote, or the reason it could not be read.
        """
        # `close` is the last traded price while a market is open and the
        # closing one after it shuts. `previousClose` covers the gap before the
        # first trade of a session, when `close` comes back as "NA".
        price = _decimal(row.get("close"))
        if price is None:
            price = _decimal(row.get("previousClose"))

        if price is None or price < 0:
            return "The provider returned no usable price for this symbol."

        price_micro = _scaled(price * (10 ** minor_digits(currency_code)), MICRO)
        if price_micro > MAX_PRICE_MICRO:
            return "The provider returned a price too large to store."

        return Quote(
            symbol=symbol,
            # The row does not say, and the stored currency is the authority.
            # Reporting it back would let a parse of our own input masquerade
            # as the provider confirming it.
            currency_code=None,
            price_micro=price_micro,
            exchange=None,
            as_of=_timestamp(row.get("timestamp")),
        )


class YahooFinanceProvider:
    """Market data from Yahoo Finance's public JSON endpoints.

    Chosen for coverage. The keyed free tiers either exclude European listings
    or charge for them, and this app is written for a household that mostly
    holds them. Yahoo asks for no key and quotes nearly every exchange.

    What that costs is worth stating plainly, because it is a real limitation
    and not a detail: these endpoints are not a documented, supported API.
    They can change shape, start refusing anonymous callers, or rate limit
    without notice, and in practice they do rate limit, per address and
    quickly. Two things follow, and both are load bearing.

    The first is that quotes are fetched in one batched request rather than one
    per symbol. A loop of single requests is what trips the limit; a portfolio
    of any normal size fits in a single call. That call wants a token Yahoo
    hands out to anything holding its cookies, so the provider does that
    handshake once and reuses the result until it stops working.

    The second is that nothing here treats a failure as fatal. The last price
    fetched stays on the instrument, the portfolio is still valued from it, and
    the page says how old it is. A provider outage makes the figures stale,
    never wrong and never absent.
    """

    def __init__(
        self,
        base_url: str,
        search_url: str,
        timeout_seconds: float,
        user_agent: str,
        batch_size: int = 100,
    ) -> None:
        """Initialize the Yahoo Finance provider.

        Args:
            base_url: The root of the finance API, without a trailing slash.
            search_url: The full URL of the symbol search endpoint.
            timeout_seconds: How long to wait for one request.
            user_agent: The User-Agent header to send. Yahoo refuses the
                default one httpx sends, so this is not decoration.
            batch_size: The most symbols to put in a single quote request.
        """
        self.base_url = base_url.rstrip("/")
        self.search_url = search_url
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.batch_size = max(1, batch_size)

    @property
    def is_configured(self) -> bool:
        """Whether this provider can actually be called.

        Returns:
            True. This provider needs no key, which is most of why it is here.
        """
        return True

    def quotes(
        self,
        symbols: Sequence[str],
        currencies: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Quote], dict[str, str]]:
        """Fetch the current price of several instruments.

        Args:
            symbols: The ticker symbols to price.
            currencies: Ignored. This provider reports the currency of every
                listing it quotes, and its answer is better than a caller's
                stored guess at it.

        Returns:
            Tuple of (quotes by symbol, reason by symbol for those that failed).

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        found, failed = self._batched_quotes(symbols)
        unreachable: PriceProviderError | None = None

        # Whatever the batch could not answer for is retried one at a time
        # against the endpoint that needs no token. That is the slow path and
        # the one the rate limit punishes, which is why it only ever sees the
        # leftovers rather than the whole portfolio.
        for symbol in list(failed):
            try:
                meta = self._meta(symbol)
            except PriceProviderError as exc:
                # Recorded rather than raised, so one unreachable retry cannot
                # throw away the prices the batch already fetched.
                unreachable = exc
                failed[symbol] = exc.message
                continue

            if isinstance(meta, str):
                failed[symbol] = meta
                continue

            quote = self._to_quote(symbol, meta)
            if isinstance(quote, Quote):
                found[symbol] = quote
                del failed[symbol]
            else:
                failed[symbol] = quote

        # Nothing at all came back and the provider was the reason. A list of
        # identical failures, one per holding, would bury that; one error says
        # it once and says a retry is worth trying.
        if not found and unreachable is not None:
            raise unreachable

        return found, failed

    def fx_rates(self, pairs: Sequence[tuple[str, str]]) -> tuple[dict[tuple[str, str], FxQuote], dict[str, str]]:
        """Fetch the rate for several currency pairs.

        Args:
            pairs: (base, quote) currency code pairs.

        Returns:
            Tuple of (rates by pair, reason by pair name for those that failed).

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        # Yahoo prices a currency pair as an instrument of its own, where
        # "EURUSD=X" is how many dollars one euro buys, so rates ride the same
        # batched request that prices do.
        symbols = {f"{base}{quote}=X": (base, quote) for base, quote in pairs}
        quoted, unquoted = self.quotes(list(symbols))

        found: dict[tuple[str, str], FxQuote] = {}
        for symbol, quote in quoted.items():
            base_code, quote_code = symbols[symbol]
            # A rate is a plain number, not an amount of money, so it is read
            # back out of the minor units the price parser put it into.
            rate_micro = quote.price_micro // (10 ** minor_digits(quote.currency_code or quote_code))

            if 0 < rate_micro <= MAX_FX_RATE_MICRO:
                found[(base_code, quote_code)] = FxQuote(
                    base_code=base_code,
                    quote_code=quote_code,
                    rate_micro=rate_micro,
                    as_of=quote.as_of,
                )
            else:
                unquoted[symbol] = "The provider returned a rate outside the range this app stores."

        failed = {f"{symbols[symbol][0]}/{symbols[symbol][1]}": reason for symbol, reason in unquoted.items()}

        return found, failed

    def search(self, query: str, limit: int) -> list[SymbolMatch]:
        """Look up listings matching a name or partial ticker.

        The search index carries no currency, so matches come back without one.
        It is filled in from the listing's first quote instead, which is the
        only place it is known for certain.

        Args:
            query: What the user typed.
            limit: The most matches to return.

        Returns:
            The matching listings.

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        payload = self._get(self.search_url, {"q": query, "quotesCount": str(limit), "newsCount": "0"})
        rows = payload.get("quotes") if isinstance(payload, dict) else None

        if not isinstance(rows, list):
            return []

        matches: list[SymbolMatch] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue

            symbol = str(row.get("symbol") or "")
            # Rows the price endpoint could not then quote are worse than rows
            # never offered, and those are exactly the ones Yahoo does not own.
            if not symbol or len(symbol) > 32 or not row.get("isYahooFinance", True):
                continue

            name = str(row.get("longname") or row.get("shortname") or symbol)
            matches.append(
                SymbolMatch(
                    symbol=symbol,
                    name=name[:255],
                    currency_code=None,
                    exchange=str(row.get("exchDisp") or row.get("exchange") or "")[:64] or None,
                    kind=_INSTRUMENT_KINDS.get(str(row.get("quoteType") or "").lower(), InstrumentKind.OTHER),
                )
            )

        return matches

    def _batched_quotes(self, symbols: Sequence[str]) -> tuple[dict[str, Quote], dict[str, str]]:
        """Fetch prices in as few requests as the batch size allows.

        Args:
            symbols: The ticker symbols to price.

        Returns:
            Tuple of (quotes by symbol, reason by symbol for those the batch
            did not answer for). A batch that fails outright reports every
            symbol in it as unanswered rather than raising, so the caller can
            fall back per symbol.
        """
        found: dict[str, Quote] = {}
        failed: dict[str, str] = {}

        for start in range(0, len(symbols), self.batch_size):
            batch = list(symbols[start : start + self.batch_size])
            answered: dict[str, Any] = {}

            try:
                payload = self._get(
                    f"{self.base_url}/v7/finance/quote",
                    {"symbols": ",".join(batch), "crumb": _crumb(self)},
                )
                rows = (payload.get("quoteResponse") or {}).get("result") if isinstance(payload, dict) else None
                if isinstance(rows, list):
                    answered = {str(row.get("symbol")): row for row in rows if isinstance(row, dict)}
            except PriceProviderError as exc:
                # The token goes stale on its own schedule, and a refusal is
                # the only signal that it has. Dropping it means the next
                # attempt does the handshake again instead of reusing a token
                # that will be refused just the same.
                _forget_crumb()
                for symbol in batch:
                    failed[symbol] = exc.message
                continue

            for symbol in batch:
                row = answered.get(symbol)
                if not isinstance(row, dict):
                    failed[symbol] = "The provider returned nothing for this symbol."
                    continue

                quote = self._to_quote(symbol, row)
                if isinstance(quote, Quote):
                    found[symbol] = quote
                else:
                    failed[symbol] = quote

        return found, failed

    def _meta(self, symbol: str) -> dict[str, Any] | str:
        """Fetch the summary Yahoo attaches to one symbol's price history.

        This is the fallback path. It needs no token, which is exactly why it
        is kept: it still answers when the handshake does not. Its cost is one
        request per symbol.

        Args:
            symbol: The ticker symbol to look up.

        Returns:
            The meta block, or the reason this symbol could not be read.

        Raises:
            PriceProviderError: If the provider cannot be reached at all.
        """
        # The symbol goes in the path, and real ones carry ".", "-", "^" and
        # "=": "BRK-B", "^GSPC", "USDEUR=X". All four are legal in a path
        # segment and are left as they are, because that is the form the
        # provider is known to answer. What is escaped is everything else,
        # which is what stops a symbol being read as more path than it is.
        payload = self._get(
            f"{self.base_url}/v8/finance/chart/{urlquote(symbol, safe='.-^=')}",
            {"range": "1d", "interval": "1d"},
        )

        chart = payload.get("chart") if isinstance(payload, dict) else None
        if not isinstance(chart, dict):
            return "The provider returned nothing for this symbol."

        error = chart.get("error")
        if isinstance(error, dict) and error:
            return str(error.get("description") or "The provider does not know this symbol.")

        results = chart.get("result")
        if not isinstance(results, list) or not results or not isinstance(results[0], dict):
            return "The provider does not know this symbol."

        meta = results[0].get("meta")
        return meta if isinstance(meta, dict) else "The provider returned no price information for this symbol."

    def _get(self, url: str, params: dict[str, str]) -> Any:
        """Make one request to the provider.

        Args:
            url: The full URL to request.
            params: Query parameters.

        Returns:
            The decoded JSON body.

        Raises:
            PriceProviderError: If the request fails or the body is not JSON.
                A 404 is not a failure here: it is how an unknown symbol is
                reported, and the body explains which, so it is returned for
                the caller to read as a per-symbol reason.
        """
        try:
            response = _client(self).get(url, params=params)

            if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                raise PriceProviderError("it is rate limiting this address. Wait a minute and try again.") from None

            if response.status_code != httpx.codes.NOT_FOUND:
                response.raise_for_status()

            return response.json()
        except httpx.HTTPStatusError as exc:
            raise PriceProviderError(f"it answered {exc.response.status_code}.", exc) from exc
        except httpx.HTTPError as exc:
            raise PriceProviderError(str(exc) or "the request failed.", exc) from exc
        except ValueError as exc:
            raise PriceProviderError("it did not answer with JSON.", exc) from exc

    def _to_quote(self, symbol: str, row: dict[str, Any]) -> Quote | str:
        """Parse one symbol's block into a quote.

        The batched endpoint and the fallback one describe a listing with the
        same field names, so one parser serves both.

        Args:
            symbol: The symbol the block belongs to.
            row: The block from the response.

        Returns:
            The quote, or the reason it could not be read.
        """
        currency = str(row.get("currency") or "").upper()
        # `regularMarketPrice` is the last traded price, and it is what stands
        # while a market is shut, which is when a portfolio is usually read.
        price = _decimal(row.get("regularMarketPrice"))

        if price is None or price < 0:
            return "The provider returned no usable price for this symbol."

        price_micro = _scaled(price * (10 ** minor_digits(currency or "EUR")), MICRO)
        if price_micro > MAX_PRICE_MICRO:
            return "The provider returned a price too large to store."

        return Quote(
            symbol=symbol,
            price_micro=price_micro,
            currency_code=currency if len(currency) == 3 else None,
            exchange=str(row.get("fullExchangeName") or row.get("exchangeName") or "")[:64] or None,
            as_of=_timestamp(row.get("regularMarketTime")),
        )


# The cookies and token a batched request needs, shared by every provider
# instance. The provider itself is built fresh for each request, so holding
# this on the instance would mean a fresh handshake on every refresh: three
# requests where one would do, against an endpoint that counts requests.
#
# The lock guards these variables, not the handshake. It is released before the
# two requests go out, so two refreshes arriving together can both do it and the
# second simply overwrites the first with an equally good token. Holding it
# across the requests would make every refresh wait on the slowest one to
# prevent a duplicate that costs almost nothing, which is the worse trade.
_CRUMB_TTL_SECONDS = 30 * 60
_crumb_lock = threading.Lock()
_crumb_value: str | None = None
_crumb_client: httpx.Client | None = None
_crumb_expires_at = 0.0


def _client(provider: "YahooFinanceProvider") -> httpx.Client:
    """Get the HTTP client the provider's requests share.

    The client is what holds Yahoo's cookies, and the cookies are half of what
    makes a batched request work, so it outlives any one request.

    Args:
        provider: The provider whose settings the client is built from.

    Returns:
        The shared client.
    """
    global _crumb_client

    with _crumb_lock:
        if _crumb_client is None:
            _crumb_client = httpx.Client(
                timeout=provider.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": provider.user_agent, "Accept": "application/json,text/plain,*/*"},
            )
        return _crumb_client


def _crumb(provider: "YahooFinanceProvider") -> str:
    """Get the token a batched quote request has to carry.

    Yahoo hands it to anything already holding its cookies, so the visit that
    collects the cookies comes first. Both are cached: the handshake is two
    requests, and doing it per refresh would cost more than it saves.

    Args:
        provider: The provider asking for the token.

    Returns:
        The token.

    Raises:
        PriceProviderError: If the handshake fails.
    """
    global _crumb_value, _crumb_expires_at

    with _crumb_lock:
        if _crumb_value and time.monotonic() < _crumb_expires_at:
            return _crumb_value

    client = _client(provider)

    try:
        # Collect the cookies. This one answers 404 by design; what matters is
        # the Set-Cookie header it sends with it.
        client.get("https://fc.yahoo.com")
        response = client.get(f"{provider.base_url}/v1/test/getcrumb")

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise PriceProviderError("it is rate limiting this address. Wait a minute and try again.") from None

        response.raise_for_status()
        value = response.text.strip()
    except httpx.HTTPStatusError as exc:
        raise PriceProviderError(f"it answered {exc.response.status_code} to the handshake.", exc) from exc
    except httpx.HTTPError as exc:
        raise PriceProviderError(str(exc) or "the handshake failed.", exc) from exc

    if not value or len(value) > 64:
        raise PriceProviderError("the handshake did not return a usable token.") from None

    with _crumb_lock:
        _crumb_value = value
        _crumb_expires_at = time.monotonic() + _CRUMB_TTL_SECONDS

    return value


def _forget_crumb() -> None:
    """Drop the cached token, so the next batched request does the handshake again."""
    global _crumb_value, _crumb_expires_at

    with _crumb_lock:
        _crumb_value = None
        _crumb_expires_at = 0.0


def _fetch_json(
    url: str,
    params: dict[str, str],
    timeout_seconds: float,
    redact: set[str] | None = None,
) -> Any:
    """Make one plain JSON request to a provider that needs no session.

    Args:
        url: The full URL to request.
        params: Query parameters.
        timeout_seconds: How long to wait.
        redact: Parameter names that must never reach an error message. An API
            token travels in the query string, and the exceptions an HTTP
            library raises quote the URL they were about. Those messages end up
            in an API response, so when anything is redacted the library's own
            wording is dropped entirely rather than filtered: a message written
            here cannot leak a parameter it never saw.

    Returns:
        The decoded JSON body.

    Raises:
        PriceProviderError: If the request fails or the body is not JSON.
    """
    secret = bool(redact)

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(url, params=params)

        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise PriceProviderError("it is rate limiting this address. Wait a minute and try again.") from None

        if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
            raise PriceProviderError("it refused the API key. Check the key and what the plan covers.") from None

        response.raise_for_status()

        return response.json()
    except httpx.HTTPStatusError as exc:
        raise PriceProviderError(f"it answered {exc.response.status_code}.", None if secret else exc) from None
    except httpx.HTTPError as exc:
        message = "the request failed." if secret else (str(exc) or "the request failed.")
        raise PriceProviderError(message, None if secret else exc) from None
    except ValueError as exc:
        raise PriceProviderError("it did not answer with JSON.", None if secret else exc) from None


def _date_or_now(value: Any) -> datetime.datetime:
    """Read the day a rate refers to.

    Args:
        value: An ISO date from the response, if there was one.

    Returns:
        Midnight on that day, or now when the provider did not say.
    """
    if isinstance(value, str):
        try:
            return datetime.datetime.combine(datetime.date.fromisoformat(value), datetime.time(), tzinfo=datetime.UTC)
        except ValueError:
            pass

    return datetime.datetime.now(datetime.UTC)


def _decimal(value: Any) -> Decimal | None:
    """Read a number exactly, whatever shape it arrived in.

    Args:
        value: The raw value from the response.

    Returns:
        The number, or None if it is missing or not a number.
    """
    if value is None or isinstance(value, bool):
        return None

    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None

    return parsed if parsed.is_finite() else None


def _scaled(value: Decimal, scale: int) -> int:
    """Multiply by a scale and round to the nearest whole unit.

    Args:
        value: The value to scale.
        scale: The scale to apply.

    Returns:
        The scaled integer, rounded half away from zero.
    """
    return int((value * scale).to_integral_value(rounding="ROUND_HALF_UP"))


def _timestamp(value: Any) -> datetime.datetime:
    """Read the moment a quote was current.

    Args:
        value: A Unix timestamp from the response, if there was one.

    Returns:
        The moment the quote refers to, or now when the provider did not say.
        Now is the safe default: it never makes a fresh price look stale.
    """
    if isinstance(value, int | float) and not isinstance(value, bool):
        try:
            return datetime.datetime.fromtimestamp(float(value), tz=datetime.UTC)
        except (OverflowError, OSError, ValueError):
            pass

    return datetime.datetime.now(datetime.UTC)
