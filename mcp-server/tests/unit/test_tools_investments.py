import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError

from hydra_mcp.client import HydraClient
from hydra_mcp.tools import _common, register_all
from tests.conftest import TOKEN, json_response
from tests.unit.test_tools import by_path
from tests.unit.test_tools_read import HOUSEHOLD, result_of

BROKER_ID = "11111111-1111-1111-1111-111111111111"
INSTRUMENT_ID = "22222222-2222-2222-2222-222222222222"
USD_INSTRUMENT_ID = "33333333-3333-3333-3333-333333333333"
TRADE_ID = "44444444-4444-4444-4444-444444444444"

ACCOUNTS = {
    "data": [
        {
            "id": BROKER_ID,
            "name": "Trade Republic",
            "type": "brokerage",
            "currency_code": "EUR",
            "current_balance_minor": 138_555,
            "institution": None,
            "archived_at": None,
        }
    ],
    "count": 1,
}

INSTRUMENTS = {
    "data": [
        {"id": INSTRUMENT_ID, "symbol": "VUAA.XETRA", "name": "Vanguard S&P 500", "currency_code": "EUR"},
        {"id": USD_INSTRUMENT_ID, "symbol": "AAPL", "name": "Apple", "currency_code": "USD"},
    ],
    "count": 2,
}


def recorded_trade(**overrides: Any) -> dict[str, Any]:
    """A trade as hydra would report it after recording one."""
    return {
        "id": TRADE_ID,
        "instrument_id": INSTRUMENT_ID,
        "symbol": "VUAA.XETRA",
        "currency_code": "EUR",
        "side": "buy",
        "traded_on": "2025-04-02",
        "quantity_micro": 5_045_714,
        "price_micro": 9_909_377_870,
        "fee_minor": 0,
        "brokerage_account_id": BROKER_ID,
        "cash_amount_minor": 50_000,
        "note": None,
        **overrides,
    }


@pytest.fixture
def authenticated() -> Iterator[None]:
    """Put a checked token on the request, the way the verifier does.

    Yields:
        Nothing; the context is torn down afterwards.
    """
    reset = auth_context_var.set(
        AuthenticatedUser(AccessToken(token=TOKEN, client_id="a-user", scopes=["hydra:read"]))
    )
    yield
    auth_context_var.reset(reset)


@pytest.fixture
def server(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Callable[[httpx.Request], httpx.Response]], MCPServer]:
    """Build a server whose tools talk to a handler rather than to a backend.

    Returns:
        A factory taking the handler and giving back the server.
    """

    def build(handler: Callable[[httpx.Request], httpx.Response]) -> MCPServer:
        monkeypatch.setattr(
            _common,
            "_client",
            HydraClient(base_url="http://hydra.test/api/v1", transport=httpx.MockTransport(handler)),
        )
        mcp: MCPServer = MCPServer("test")
        register_all(mcp)
        return mcp

    return build


def investing(
    answer: dict[str, Any] | None = None, *, trades: dict[str, Any] | None = None
) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    """Answer the reference data, and whatever is written, keeping the requests."""
    seen: list[httpx.Request] = []
    reference = {
        "/households/me": HOUSEHOLD,
        "/accounts/": ACCOUNTS,
        "/investments/instruments": INSTRUMENTS,
        "/investments/trades": trades or {"data": [], "count": 0},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            for path, payload in reference.items():
                if request.url.path.endswith(path):
                    return json_response(200, payload)
            return json_response(404, {"detail": "no stub"})
        return json_response(200, answer if answer is not None else recorded_trade())

    return handler, seen


def written(seen: list[httpx.Request]) -> dict[str, Any]:
    """The body of the one request that was not a read."""
    for request in seen:
        if request.method != "GET":
            body: dict[str, Any] = json.loads(request.content)
            return body
    raise AssertionError("nothing was written")


def a_buy(**overrides: Any) -> dict[str, Any]:
    """The arguments for a savings plan execution, as a statement reads."""
    return {
        "symbol": "VUAA",
        "side": "buy",
        "traded_on": "2025-04-02",
        "quantity": "5.045714",
        "total": "500.00",
        "brokerage_account": "Trade Republic",
        **overrides,
    }


class TestRecordTrade:
    """Tests for recording a buy or a sell."""

    async def test_sends_the_quantity_in_millionths(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy())

        assert written(seen)["quantity_micro"] == 5_045_714

    async def test_finds_a_listing_by_its_bare_symbol(self, server: Any, authenticated: None) -> None:
        # A statement names no exchange, so VUAA has to find VUAA.XETRA.
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy())

        assert written(seen)["instrument_id"] == INSTRUMENT_ID

    async def test_works_the_price_out_from_the_total(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy())

        body = written(seen)
        # What hydra will make of it: quantity times price, in minor units.
        cost_minor = body["quantity_micro"] * body["price_micro"] / 10**12
        assert round(cost_minor) == 50_000

    async def test_takes_the_fee_out_before_pricing_a_buy(self, server: Any, authenticated: None) -> None:
        # hydra adds the fee back onto the cost, so it must not be in the price.
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy(quantity="1", total="112.44", fee="1.00"))

        body = written(seen)
        assert body["price_micro"] == 11_144_000_000
        assert body["fee_minor"] == 100

    async def test_adds_the_fee_back_before_pricing_a_sell(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy(side="sell", quantity="1", total="99.00", fee="1.00"))

        assert written(seen)["price_micro"] == 10_000_000_000

    async def test_the_cash_is_what_the_statement_says(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy())

        body = written(seen)
        assert body["brokerage_account_id"] == BROKER_ID
        assert body["cash_amount_minor"] == 50_000

    async def test_a_given_price_is_held_in_minor_units(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy(price="99.0942"))

        assert written(seen)["price_micro"] == 9_909_420_000

    async def test_without_a_brokerage_account_no_cash_moves(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        await server(handler).call_tool("record_trade", a_buy(brokerage_account=None))

        body = written(seen)
        assert "brokerage_account_id" not in body
        assert "cash_amount_minor" not in body

    async def test_will_not_price_a_foreign_listing_from_a_euro_total(self, server: Any, authenticated: None) -> None:
        handler, seen = investing()

        with pytest.raises(ToolError, match="quotes in USD"):
            await server(handler).call_tool("record_trade", a_buy(symbol="AAPL"))

        assert all(request.method == "GET" for request in seen)

    async def test_needs_a_total_or_a_price(self, server: Any, authenticated: None) -> None:
        handler, _ = investing()

        with pytest.raises(ToolError, match="Give the total"):
            await server(handler).call_tool("record_trade", a_buy(total=None))

    async def test_refuses_a_quantity_finer_than_a_millionth(self, server: Any, authenticated: None) -> None:
        handler, _ = investing()

        with pytest.raises(ToolError, match="more precise"):
            await server(handler).call_tool("record_trade", a_buy(quantity="1.0000001"))

    async def test_an_unknown_symbol_says_what_is_tracked(self, server: Any, authenticated: None) -> None:
        handler, _ = investing()

        with pytest.raises(ToolError, match="AAPL"):
            await server(handler).call_tool("record_trade", a_buy(symbol="MSFT"))

    async def test_reports_the_trade_in_major_units(self, server: Any, authenticated: None) -> None:
        handler, _ = investing()

        trade = result_of(await server(handler).call_tool("record_trade", a_buy()))

        assert trade["quantity"] == "5.045714"
        assert trade["price"] == "99.0937787"
        assert trade["brokerage_account"] == "Trade Republic"
        assert trade["cash"]["display"] == "-€500.00"


class TestListTrades:
    """Tests for reading what is already recorded."""

    async def test_filters_on_the_instrument(self, server: Any, authenticated: None) -> None:
        handler, seen = investing(trades={"data": [recorded_trade()], "count": 1})

        listed = result_of(await server(handler).call_tool("list_trades", {"symbol": "VUAA"}))

        trades = next(request for request in seen if request.url.path.endswith("/investments/trades"))
        assert trades.url.params["instrument_id"] == INSTRUMENT_ID
        assert listed["count"] == 1

    async def test_a_sale_puts_cash_back(self, server: Any, authenticated: None) -> None:
        handler, _ = investing(trades={"data": [recorded_trade(side="sell")], "count": 1})

        listed = result_of(await server(handler).call_tool("list_trades", {}))

        assert listed["trades"][0]["cash"]["display"] == "€500.00"


class TestDeleteTrade:
    """Tests for removing a trade."""

    async def test_asks_hydra_to_delete_it(self, server: Any, authenticated: None) -> None:
        handler, seen = investing({"message": "Trade deleted."})

        await server(handler).call_tool("delete_trade", {"trade_id": TRADE_ID})

        request = next(request for request in seen if request.method != "GET")
        assert request.method == "DELETE"
        assert request.url.path.endswith(f"/investments/trades/{TRADE_ID}")


class TestGetPortfolio:
    """Tests for valuing the holdings."""

    async def test_the_last_price_is_in_major_units(self, server: Any, authenticated: None) -> None:
        # hydra holds a price in minor units times a million: 128.4567 EUR is
        # 12_845_670_000, and reading it as plain millionths is a hundredfold out.
        portfolio = {
            "currency_code": "EUR",
            "data": [
                {
                    "symbol": "VUAA.XETRA",
                    "name": "Vanguard S&P 500",
                    "quantity_micro": 1_000_000,
                    "currency_code": "EUR",
                    "last_price_micro": 12_845_670_000,
                    "cost_basis_minor": 10_000,
                    "market_value_minor": 12_846,
                    "unrealised_gain_minor": 2_846,
                    "realised_gain_minor": 0,
                    "is_open": True,
                }
            ],
            "total_cost_basis_minor": 10_000,
            "total_market_value_minor": 12_846,
            "total_unrealised_gain_minor": 2_846,
            "total_realised_gain_minor": 0,
            "unpriced_count": 0,
        }
        mcp = server(by_path({"/investments/portfolio": portfolio}))

        result = result_of(await mcp.call_tool("get_portfolio", {}))

        assert result["holdings"][0]["last_price"] == "128.4567"
