import datetime
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

HOUSEHOLD = {"name": "Home", "currency_code": "EUR", "member_count": 2}

ACCOUNTS = {
    "data": [
        {
            "id": "8d538630-1dec-4735-98b7-d7d2c09ba4aa",
            "name": "Current",
            "type": "current",
            "currency_code": "EUR",
            "current_balance_minor": 1_720_498,
            "institution": "Alpha Bank",
            "archived_at": None,
        }
    ],
    "count": 1,
    "total_balance_minor": 1_720_498,
}

SUMMARY = {
    "period": {"date_from": "2026-09-01", "date_to": "2026-09-30", "currency_code": "EUR"},
    "income_minor": 327_500,
    "expense_minor": 142_365,
    "net_minor": 185_135,
    "bank_minor": 2_556_526,
    "brokerage_minor": 0,
    "assets_minor": 1_329_738,
    "net_worth_minor": 3_886_264,
    "unpriced_asset_count": 0,
    "budgeted_minor": 0,
    "over_budget_category_count": 1,
    "transaction_count": 12,
    "top_categories": [
        {
            "category_id": "c1",
            "category_name": "Groceries",
            "parent_id": None,
            "parent_name": "Food",
            "color": None,
            "amount_minor": 42_350,
            "transaction_count": 7,
            "share": 0.2975,
        }
    ],
}


@pytest.fixture
def authenticated() -> Iterator[None]:
    """Put a checked token on the request, the way the verifier does.

    Yields:
        Nothing; the context is torn down afterwards.
    """
    access_token = AccessToken(token=TOKEN, client_id="a-user", scopes=["hydra:read"])
    reset = auth_context_var.set(AuthenticatedUser(access_token))
    yield
    auth_context_var.reset(reset)


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Callable[[Callable[[httpx.Request], httpx.Response]], MCPServer]:
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


def by_path(routes: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """Answer each path with the payload it is mapped to."""

    def handler(request: httpx.Request) -> httpx.Response:
        for path, payload in routes.items():
            if request.url.path.endswith(path):
                return json_response(200, payload)
        return json_response(404, {"detail": f"no stub for {request.url.path}"})

    return handler


def result_of(call: Any) -> Any:
    """Read the structured payload out of a tool result."""
    assert not call.is_error, call.content
    return call.structured_content


class TestWhoami:
    """Tests for the tool that says whose household this is."""

    async def test_reports_the_person_and_their_household(self, server: Any, authenticated: None) -> None:
        mcp = server(
            by_path(
                {
                    "/users/me": {"id": "u1", "email": "test@example.com", "full_name": "Test"},
                    "/households/me": HOUSEHOLD,
                }
            )
        )

        assert result_of(await mcp.call_tool("whoami", {})) == {
            "email": "test@example.com",
            "name": "Test",
            "household": "Home",
            "currency": "EUR",
            "member_count": 2,
        }


class TestListAccounts:
    """Tests for the account listing."""

    async def test_reports_a_balance_every_useful_way(self, server: Any, authenticated: None) -> None:
        mcp = server(by_path({"/accounts/": ACCOUNTS, "/households/me": HOUSEHOLD}))

        accounts = result_of(await mcp.call_tool("list_accounts", {}))["accounts"]

        assert accounts[0]["balance"] == {
            "amount": "17204.98",
            "display": "€17204.98",
            "amount_minor": 1_720_498,
            "currency": "EUR",
        }

    async def test_a_negative_balance_carries_its_sign(self, server: Any, authenticated: None) -> None:
        overdrawn = {**ACCOUNTS, "data": [{**ACCOUNTS["data"][0], "current_balance_minor": -5000}]}
        mcp = server(by_path({"/accounts/": overdrawn, "/households/me": HOUSEHOLD}))

        accounts = result_of(await mcp.call_tool("list_accounts", {}))["accounts"]

        assert accounts[0]["balance"]["display"] == "-€50.00"

    async def test_archived_accounts_are_left_out_unless_asked_for(self, server: Any, authenticated: None) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/households/me"):
                return json_response(200, HOUSEHOLD)
            seen.append(request.url.query.decode())
            return json_response(200, ACCOUNTS)

        mcp = server(handler)
        await mcp.call_tool("list_accounts", {})
        await mcp.call_tool("list_accounts", {"include_archived": True})

        assert seen == ["include_archived=false", "include_archived=true"]

    async def test_the_total_is_labelled_with_the_household_currency(
        self, server: Any, authenticated: None
    ) -> None:
        # The total is in the household currency whatever the accounts hold,
        # so reading it off the first account labels a mixed household by
        # whichever one came first.
        in_dollars = {**ACCOUNTS, "data": [{**ACCOUNTS["data"][0], "currency_code": "USD"}]}
        mcp = server(by_path({"/accounts/": in_dollars, "/households/me": HOUSEHOLD}))

        listed = result_of(await mcp.call_tool("list_accounts", {}))

        assert listed["total"]["currency"] == "EUR"

    async def test_an_empty_household_does_not_guess_a_currency(self, server: Any, authenticated: None) -> None:
        # With no account to read one off, the old code fell back to euros for
        # everybody, and the instructions say never to assume a currency.
        empty = {"data": [], "count": 0, "total_balance_minor": 0}
        mcp = server(by_path({"/accounts/": empty, "/households/me": {**HOUSEHOLD, "currency_code": "GBP"}}))

        listed = result_of(await mcp.call_tool("list_accounts", {}))

        assert listed["total"]["currency"] == "GBP"


class TestMonthSummary:
    """Tests for the month summary."""

    async def test_defaults_to_the_current_month(self, server: Any, authenticated: None) -> None:
        # Left to the caller this is a guess, and hydra rejects a malformed
        # month rather than assuming one.
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.query.decode())
            return json_response(200, SUMMARY)

        await server(handler).call_tool("get_month_summary", {})

        assert seen == [f"month={datetime.date.today():%Y-%m}"]

    async def test_asks_for_the_month_it_was_given(self, server: Any, authenticated: None) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.query.decode())
            return json_response(200, SUMMARY)

        await server(handler).call_tool("get_month_summary", {"month": "2026-01"})

        assert seen == ["month=2026-01"]

    async def test_refuses_a_month_that_is_not_one(self, server: Any, authenticated: None) -> None:
        # Checked against the schema before the tool runs, so a month hydra
        # would reject never becomes a request.
        mcp = server(by_path({"/reports/summary": SUMMARY}))

        with pytest.raises(ToolError, match="month"):
            await mcp.call_tool("get_month_summary", {"month": "last month"})

    async def test_spending_reads_as_money_going_out(self, server: Any, authenticated: None) -> None:
        mcp = server(by_path({"/reports/summary": SUMMARY}))

        summary = result_of(await mcp.call_tool("get_month_summary", {}))

        assert summary["expense"]["display"] == "-€1423.65"
        assert summary["expense"]["amount"] == "1423.65"

    async def test_a_net_keeps_its_own_sign(self, server: Any, authenticated: None) -> None:
        # Unlike a transaction, a total is genuinely negative in a month that
        # spent more than it earned.
        overspent = {**SUMMARY, "net_minor": -185_135}
        mcp = server(by_path({"/reports/summary": overspent}))

        summary = result_of(await mcp.call_tool("get_month_summary", {}))

        assert summary["net"]["display"] == "-€1851.35"

    async def test_a_share_is_reported_as_a_percentage(self, server: Any, authenticated: None) -> None:
        mcp = server(by_path({"/reports/summary": SUMMARY}))

        summary = result_of(await mcp.call_tool("get_month_summary", {}))

        assert summary["top_categories"][0]["share"] == "29.8%"


class TestEveryToolOnlyReads:
    """The read-only promise is what a client shows its user."""

    async def test_every_tool_says_so(self, server: Any) -> None:
        mcp = server(by_path({}))

        for tool in await mcp.list_tools():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name


class TestWithoutACredential:
    """A tool reached without one must say so rather than guess."""

    async def test_says_no_token_arrived(self, server: Any) -> None:
        mcp = server(by_path({"/users/me": {"id": "u1", "email": "a@b.c", "full_name": None}}))

        with pytest.raises(ToolError, match="no hydra API token"):
            await mcp.call_tool("whoami", {})
