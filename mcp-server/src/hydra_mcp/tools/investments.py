import datetime
import uuid
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Literal, cast

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..money import exponent_of, money, signed_money, to_minor
from ..resolve import PAGE_SIZE, Named, accounts_of
from ._common import DESTRUCTIVE, READ_ONLY, WRITES, as_str, current_token, hydra

# Quantities and prices are stored as millionths, the way money is stored as
# minor units: an exact integer rather than a float that drifts.
MICRO = Decimal(1_000_000)

Quantity = Annotated[
    str,
    Field(description="How many units, always positive, as the broker reports it, for example 5.045714."),
]


def register(mcp: MCPServer) -> None:
    """Register the investment tools.

    Args:
        mcp: The server to register them on.
    """

    @mcp.tool(annotations=READ_ONLY)
    async def get_portfolio(
        include_closed: Annotated[
            bool, Field(description="Include holdings that have been sold off entirely.")
        ] = False,
    ) -> dict[str, Any]:
        """Value the household's investments.

        Everything is converted into the household currency. A holding with no
        recent price contributes nothing, so a total with any of those is an
        understatement rather than an error, which is why they are counted.

        Args:
            include_closed: Whether fully sold holdings are listed too.

        Returns:
            Each holding and what the portfolio is worth.
        """
        payload = await hydra().get(
            "/investments/portfolio",
            token=current_token(),
            subject="portfolio",
            params={"include_closed": include_closed},
        )

        currency = payload["currency_code"]

        return {
            "currency": currency,
            "holdings": [_position(position, currency) for position in payload["data"]],
            "cost_basis": money(payload["total_cost_basis_minor"], currency),
            "market_value": money(payload["total_market_value_minor"], currency),
            "unrealised_gain": signed_money(payload["total_unrealised_gain_minor"], currency),
            "realised_gain": signed_money(payload["total_realised_gain_minor"], currency),
            # Holdings with no price or no exchange rate. They are worth
            # nothing in the totals above, so any of these means the portfolio
            # is worth more than it says.
            "unpriced_holdings": payload["unpriced_count"],
            "priced_as_of": payload.get("priced_as_of"),
        }

    @mcp.tool(annotations=READ_ONLY)
    async def list_trades(
        symbol: Annotated[
            str | None, Field(description="Only the trades in this instrument, by symbol. Leave it out for all.")
        ] = None,
    ) -> dict[str, Any]:
        """List the buys and sells already recorded, newest first.

        Read this before recording trades from a statement: a trade recorded
        twice doubles the holding and takes its cash out of the broker twice.

        Args:
            symbol: The instrument to list the trades of.

        Returns:
            The trades, and how many there are.
        """
        token = current_token()
        accounts = await accounts_of(token)
        currency = await _household_currency(token)

        params: dict[str, Any] = {}
        if symbol is not None:
            params["instrument_id"] = str(_resolve(await _instruments_of(token), symbol)["id"])

        trades = await _trades_of(token, params)

        return {
            "trades": [_trade(trade, accounts, currency) for trade in trades],
            "count": len(trades),
        }

    @mcp.tool(annotations=WRITES)
    async def record_trade(
        symbol: Annotated[
            str, Field(description="The instrument, by the symbol it is tracked under, for example VUAA.")
        ],
        side: Annotated[Literal["buy", "sell"], Field(description="Whether units were bought or sold.")],
        traded_on: Annotated[datetime.date, Field(description="The day the trade was executed.")],
        quantity: Quantity,
        total: Annotated[
            str | None,
            Field(
                description=(
                    "What left the brokerage account on a buy, or reached it on a sell, in the household "
                    "currency and with any fee included. The figure on the broker's statement, for example 500.00."
                )
            ),
        ] = None,
        price: Annotated[
            str | None,
            Field(
                description=(
                    "The price of one unit, in the instrument's own currency, for example 99.0942. "
                    "Leave it out to work it out from the total, which only works when the instrument "
                    "quotes in the household currency."
                )
            ),
        ] = None,
        fee: Annotated[
            str | None,
            Field(description="Commission and taxes, in the instrument's own currency, for example 1.00."),
        ] = None,
        brokerage_account: Annotated[
            str | None,
            Field(description="The brokerage account the cash moved through, by name."),
        ] = None,
        note: Annotated[str | None, Field(description="Anything worth remembering about it.", max_length=1024)] = None,
    ) -> dict[str, Any]:
        """Record a buy or a sell of an instrument the household already tracks.

        This records a trade that already happened. It does not place an order
        anywhere.

        The quantity is positive; `side` says which way the units moved. Give
        the total from the statement, and the price is worked out from it, so
        the cost basis and the brokerage cash both match what the broker
        charged. Name the brokerage account so the cash leaves it on a buy and
        lands in it on a sell; without one only the holding changes.

        Args:
            symbol: The instrument traded.
            side: buy or sell.
            traded_on: The day it was executed.
            quantity: How many units, positive.
            total: What moved in cash, in the household currency, fee included.
            price: The price of one unit, in the instrument's currency.
            fee: Commission and taxes, in the instrument's currency.
            brokerage_account: The brokerage account the cash moved through.
            note: Anything worth remembering.

        Returns:
            The trade as recorded.
        """
        token = current_token()
        instrument = _resolve(await _instruments_of(token), symbol)
        accounts = await accounts_of(token)
        household_currency = await _household_currency(token)
        instrument_currency = instrument["currency_code"]

        quantity_micro = _to_micro(quantity, "quantity")
        if quantity_micro == 0:
            raise ToolError("A trade moves at least some units, so the quantity cannot be zero.")

        fee_minor = to_minor(fee, instrument_currency) if fee is not None else 0
        total_minor = to_minor(total, household_currency) if total is not None else None

        if price is not None:
            price_micro = _to_micro(price, "price", exponent=exponent_of(instrument_currency))
        elif total_minor is None:
            raise ToolError("Give the total from the statement, or the price of one unit, so the trade has a cost.")
        elif instrument_currency != household_currency:
            raise ToolError(
                f"{instrument['symbol']} quotes in {instrument_currency}, not {household_currency}, so its price "
                f"cannot be worked out from a {household_currency} total. Give the price in {instrument_currency} "
                "as well as the total."
            )
        else:
            price_micro = _price_from_total(
                side=side, total_minor=total_minor, fee_minor=fee_minor, quantity_micro=quantity_micro
            )

        body: dict[str, Any] = {
            "instrument_id": instrument["id"],
            "side": side,
            "traded_on": traded_on.isoformat(),
            "quantity_micro": quantity_micro,
            "price_micro": price_micro,
            "fee_minor": fee_minor,
        }
        if brokerage_account is not None:
            body["brokerage_account_id"] = as_str(accounts.id(brokerage_account))
            # What the broker actually charged, rather than hydra's own
            # estimate from a reference exchange rate.
            if total_minor is not None:
                body["cash_amount_minor"] = total_minor
        if note is not None:
            body["note"] = note

        payload = await hydra().post(
            "/investments/trades", token=token, subject="instrument or brokerage account", json=body
        )

        return _trade(payload, accounts, household_currency)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def delete_trade(
        trade_id: Annotated[str, Field(description="The id, from list_trades.")],
    ) -> dict[str, Any]:
        """Delete a recorded trade.

        The holding and the brokerage cash both move back as if it had never
        been recorded. Check with the person before calling this on anything
        you did not just record yourself.

        Args:
            trade_id: Which trade.

        Returns:
            What hydra said about the deletion.
        """
        answer: dict[str, Any] = await hydra().delete(
            f"/investments/trades/{trade_id}", token=current_token(), subject="trade"
        )
        return answer


async def _household_currency(token: str) -> str:
    """Fetch the currency the household reports in.

    Args:
        token: The hydra API token to present.

    Returns:
        The ISO 4217 code.
    """
    household = await hydra().get("/households/me", token=token, subject="household")
    currency: str = household["currency_code"]
    return currency


async def _instruments_of(token: str) -> list[dict[str, Any]]:
    """Fetch every instrument the household tracks.

    Args:
        token: The hydra API token to present.

    Returns:
        The instruments, as hydra reports them.
    """
    return await _paged(token, "/investments/instruments", subject="instrument", params={})


async def _trades_of(token: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch every recorded trade, newest first.

    Args:
        token: The hydra API token to present.
        params: Filters to pass on.

    Returns:
        The trades, as hydra reports them.
    """
    return await _paged(token, "/investments/trades", subject="trade", params=params)


async def _paged(token: str, path: str, *, subject: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Read a listing to the end, a page at a time.

    Args:
        token: The hydra API token to present.
        path: The listing to read.
        subject: What is being listed, for the not-found message.
        params: Filters to pass on.

    Returns:
        Every row.
    """
    rows: list[dict[str, Any]] = []
    while True:
        payload = await hydra().get(
            path, token=token, subject=subject, params={**params, "skip": len(rows), "limit": PAGE_SIZE}
        )
        page = payload["data"]
        rows.extend(page)
        if not page or len(rows) >= payload["count"]:
            return rows


def _resolve(instruments: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    """Find the instrument a caller means.

    The symbol is matched without regard to case. A listing tracked as
    "VUAA.XETRA" is also found as "VUAA", as long as no other listing of it is
    tracked, because the caller is reading a statement that names no exchange.

    Args:
        instruments: The instruments the household tracks.
        symbol: The symbol, or an id from an earlier result.

    Returns:
        The instrument.

    Raises:
        ToolError: If none matches, or more than one does.
    """
    by_id = {uuid.UUID(instrument["id"]): instrument for instrument in instruments}
    symbols = Named({key: value["symbol"] for key, value in by_id.items()}, "instrument")

    wanted = symbol.strip().lower()
    if not any(instrument["symbol"].lower() == wanted for instrument in instruments):
        listings = [i for i in instruments if i["symbol"].lower().split(".", 1)[0] == wanted]
        if len(listings) == 1:
            return listings[0]
        if len(listings) > 1:
            options = ", ".join(sorted(i["symbol"] for i in listings))
            raise ToolError(f"More than one listing of '{symbol}' is tracked. Say which one: {options}.")

    # Named raises on a miss, naming the closest symbols. It only answers None
    # when it was asked for nothing, which a symbol never is.
    return by_id[cast(uuid.UUID, symbols.id(symbol))]


def _trade(trade: dict[str, Any], accounts: Named, household_currency: str) -> dict[str, Any]:
    """Describe one trade.

    Args:
        trade: The trade as hydra reports it.
        accounts: The household's accounts, to name the brokerage account.
        household_currency: The currency the cash side is in.

    Returns:
        The fields worth reading.
    """
    currency = trade["currency_code"]
    cash_minor = trade.get("cash_amount_minor")

    return {
        "id": trade["id"],
        "symbol": trade["symbol"],
        "side": trade["side"],
        "traded_on": trade["traded_on"],
        "quantity": _from_micro(trade["quantity_micro"]),
        "price": _price(trade["price_micro"], currency),
        "currency": currency,
        "fee": money(trade["fee_minor"], currency),
        "brokerage_account": accounts.name(trade.get("brokerage_account_id")),
        # What moved through the brokerage account. Out on a buy, in on a sell.
        "cash": money(cash_minor, household_currency, negative=trade["side"] == "buy")
        if cash_minor is not None
        else None,
        "note": trade.get("note"),
    }


def _position(position: dict[str, Any], currency: str) -> dict[str, Any]:
    """Describe one holding.

    Args:
        position: The position as hydra reports it.
        currency: The household currency the values are in.

    Returns:
        The fields worth reading.
    """
    return {
        "symbol": position["symbol"],
        "name": position.get("name"),
        "quantity": _from_micro(position["quantity_micro"]),
        "currency": position["currency_code"],
        "last_price": _price(position.get("last_price_micro"), position["currency_code"]),
        "last_price_at": position.get("last_price_at"),
        # A hand-entered price is only as fresh as whoever typed it.
        "price_is_manual": position.get("last_price_is_manual", False),
        "cost_basis": money(position["cost_basis_minor"], currency),
        "market_value": money(position["market_value_minor"], currency),
        "unrealised_gain": signed_money(position["unrealised_gain_minor"], currency),
        "realised_gain": signed_money(position["realised_gain_minor"], currency),
        "open": position["is_open"],
    }


def _from_micro(value: int | None) -> str | None:
    """Render a quantity held as millionths.

    Args:
        value: The stored integer, or None.

    Returns:
        The number as text, with trailing zeroes trimmed, or None.
    """
    if value is None:
        return None

    exact = (Decimal(value) / MICRO).normalize()
    return f"{exact:f}"


def _price(value: int | None, currency_code: str) -> str | None:
    """Render a unit price, which is held as millionths of a minor unit.

    Args:
        value: The stored integer, or None when there is no price.
        currency_code: The instrument's currency.

    Returns:
        The price in major units, with trailing zeroes trimmed, or None.
    """
    if value is None:
        return None

    exact = (Decimal(value) / MICRO).scaleb(-exponent_of(currency_code)).normalize()
    return f"{exact:f}"


def _to_micro(number: str, what: str, *, exponent: int = 0) -> int:
    """Read a number a caller wrote into millionths.

    Args:
        number: The number as written.
        what: What it is, for the error message.
        exponent: How many places to shift it first: a price is held in minor
            units, so it is shifted by the currency's decimal places.

    Returns:
        The number, shifted, times a million.

    Raises:
        ToolError: If it is not a number, is negative, or is finer than can be stored.
    """
    try:
        value = Decimal(number)
    except InvalidOperation:
        raise ToolError(f"'{number}' is not a {what}. Write it as a number, for example 5.045714.") from None

    if not value.is_finite() or value < 0:
        raise ToolError(f"A {what} is always a positive number: {number} is not one.")

    scaled = value.scaleb(exponent) * MICRO
    if scaled != scaled.to_integral_value():
        raise ToolError(f"A {what} of {number} is more precise than hydra can store exactly.")

    return int(scaled)


def _price_from_total(*, side: str, total_minor: int, fee_minor: int, quantity_micro: int) -> int:
    """Work out the unit price from what the broker charged.

    A fee is part of what a buy cost and comes off what a sale returned, which
    is how hydra adds it back, so it is taken out here first and the cost basis
    then comes to the total exactly.

    Args:
        side: buy or sell.
        total_minor: What moved in cash, in minor units.
        fee_minor: The fee, in minor units.
        quantity_micro: The units traded, times a million.

    Returns:
        The price of one unit, in minor units times a million.

    Raises:
        ToolError: If the fee is larger than what a buy cost.
    """
    gross_minor = total_minor - fee_minor if side == "buy" else total_minor + fee_minor
    if gross_minor < 0:
        raise ToolError("The fee is larger than the total, so there is nothing left to have paid for the units.")

    price = Decimal(gross_minor) * MICRO * MICRO / Decimal(quantity_micro)
    return int(price.quantize(Decimal(1), rounding=ROUND_HALF_UP))
