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

ACCOUNT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER_ACCOUNT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PARENT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
CHILD_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"

ACCOUNTS = {
    "data": [
        {
            "id": ACCOUNT_ID,
            "name": "Current",
            "type": "current",
            "currency_code": "EUR",
            "current_balance_minor": 100_000,
            "institution": None,
            "archived_at": None,
        },
        {
            "id": OTHER_ACCOUNT_ID,
            "name": "Savings",
            "type": "savings",
            "currency_code": "EUR",
            "current_balance_minor": 500_000,
            "institution": None,
            "archived_at": None,
        },
    ],
    "count": 2,
    "total_balance_minor": 600_000,
}

TREE = {
    "data": [
        {
            "id": PARENT_ID,
            "name": "Food & Drink",
            "kind": "expense",
            "archived_at": None,
            "children": [
                {"id": CHILD_ID, "name": "Groceries", "kind": "expense", "archived_at": None},
            ],
        }
    ],
    "count": 1,
}

TRANSACTIONS = {
    "data": [
        {
            "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "kind": "expense",
            "amount_minor": 9_317,
            "occurred_on": "2026-09-02",
            "account_id": ACCOUNT_ID,
            "category_id": CHILD_ID,
            "counter_account_id": None,
            "merchant": "The shop",
            "note": None,
            "is_generated": False,
        }
    ],
    "count": 1,
}

BUDGET_PROGRESS = {
    "period": {"date_from": "2026-09-01", "date_to": "2026-09-30", "currency_code": "EUR"},
    "total_limit_minor": 100_000,
    "total_spent_minor": 120_000,
    "total_remaining_minor": -20_000,
    "unbudgeted_spend_minor": 5_000,
    "rows": [
        {
            "budget_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "category_id": PARENT_ID,
            "category_name": "Food & Drink",
            "parent_id": None,
            "covers_subcategories": True,
            "limit_minor": 100_000,
            "spent_minor": 120_000,
            "remaining_minor": -20_000,
            "progress": 1.2,
            "is_over_budget": True,
        }
    ],
}


@pytest.fixture
def authenticated() -> Iterator[None]:
    """Put a checked token on the request, the way the verifier does.

    Yields:
        Nothing; the context is torn down afterwards.
    """
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token=TOKEN, client_id="a-user", scopes=["hydra:read"])))
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


def routes(**extra: Any) -> Callable[[httpx.Request], httpx.Response]:
    """Answer the reference data plus whatever a test adds."""
    table: dict[str, Any] = {
        "/households/me": HOUSEHOLD,
        "/accounts/": ACCOUNTS,
        "/categories/tree": TREE,
        **extra,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        for path, payload in table.items():
            if request.url.path.endswith(path):
                return json_response(200, payload)
        return json_response(404, {"detail": f"no stub for {request.url.path}"})

    return handler


def recorded(**extra: Any) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    """Answer as above, and keep every request for inspection."""
    seen: list[httpx.Request] = []
    inner = routes(**extra)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return inner(request)

    return handler, seen


def result_of(call: Any) -> Any:
    """Read the structured payload out of a tool result."""
    assert not call.is_error, call.content
    return call.structured_content


def query_for(seen: list[httpx.Request], path: str) -> dict[str, str]:
    """Get the query string the tool sent to one endpoint."""
    for request in seen:
        if request.url.path.endswith(path):
            return dict(request.url.params)
    raise AssertionError(f"{path} was never requested")


class TestListCategories:
    """Tests for the category listing."""

    async def test_writes_a_child_under_its_parent(self, server: Any, authenticated: None) -> None:
        # Which is the name every other tool accepts for it.
        listed = result_of(await server(routes()).call_tool("list_categories", {}))

        assert [c["name"] for c in listed["categories"]] == ["Food & Drink", "Food & Drink > Groceries"]


class TestSearchTransactions:
    """Tests for the transaction search."""

    async def test_reports_names_rather_than_ids(self, server: Any, authenticated: None) -> None:
        found = result_of(await server(routes(**{"/transactions/": TRANSACTIONS})).call_tool("search_transactions", {}))

        assert found["transactions"][0]["account"] == "Current"
        assert found["transactions"][0]["category"] == "Groceries"

    async def test_spending_reads_as_money_going_out(self, server: Any, authenticated: None) -> None:
        found = result_of(await server(routes(**{"/transactions/": TRANSACTIONS})).call_tool("search_transactions", {}))

        assert found["transactions"][0]["amount"]["display"] == "-€93.17"
        assert found["transactions"][0]["amount"]["amount"] == "93.17"

    async def test_turns_a_category_name_into_the_id_hydra_wants(self, server: Any, authenticated: None) -> None:
        handler, seen = recorded(**{"/transactions/": TRANSACTIONS})

        await server(handler).call_tool("search_transactions", {"category": "Groceries"})

        assert query_for(seen, "/transactions/")["category_id"] == CHILD_ID

    async def test_turns_an_account_name_into_the_id_hydra_wants(self, server: Any, authenticated: None) -> None:
        handler, seen = recorded(**{"/transactions/": TRANSACTIONS})

        await server(handler).call_tool("search_transactions", {"account": "Savings"})

        assert query_for(seen, "/transactions/")["account_id"] == OTHER_ACCOUNT_ID

    async def test_turns_an_amount_into_minor_units(self, server: Any, authenticated: None) -> None:
        handler, seen = recorded(**{"/transactions/": TRANSACTIONS})

        await server(handler).call_tool("search_transactions", {"min_amount": "20.00"})

        assert query_for(seen, "/transactions/")["min_amount_minor"] == "2000"

    async def test_refuses_an_amount_the_currency_cannot_hold(self, server: Any, authenticated: None) -> None:
        mcp = server(routes(**{"/transactions/": TRANSACTIONS}))

        with pytest.raises(ToolError, match="2 decimal places"):
            await mcp.call_tool("search_transactions", {"min_amount": "20.005"})

    async def test_an_unknown_category_says_what_exists(self, server: Any, authenticated: None) -> None:
        mcp = server(routes(**{"/transactions/": TRANSACTIONS}))

        with pytest.raises(ToolError, match="no category called 'Groserys'"):
            await mcp.call_tool("search_transactions", {"category": "Groserys"})

    async def test_sends_no_filter_it_was_not_given(self, server: Any, authenticated: None) -> None:
        # "?category_id=None" would be a 422 rather than the absence meant.
        handler, seen = recorded(**{"/transactions/": TRANSACTIONS})

        await server(handler).call_tool("search_transactions", {})

        assert "category_id" not in query_for(seen, "/transactions/")


class TestBudgetProgress:
    """Tests for the budget comparison."""

    async def test_an_overspent_category_reads_as_negative(self, server: Any, authenticated: None) -> None:
        # What is left of a budget is a real negative, unlike a transaction.
        progress = result_of(
            await server(routes(**{"/reports/budget-progress": BUDGET_PROGRESS})).call_tool("get_budget_progress", {})
        )

        assert progress["categories"][0]["remaining"]["display"] == "-€200.00"
        assert progress["total_remaining"]["display"] == "-€200.00"

    async def test_says_how_much_of_the_limit_is_used(self, server: Any, authenticated: None) -> None:
        progress = result_of(
            await server(routes(**{"/reports/budget-progress": BUDGET_PROGRESS})).call_tool("get_budget_progress", {})
        )

        assert progress["categories"][0]["used"] == "120.0%"
        assert progress["categories"][0]["over_budget"] is True

    async def test_keeps_spending_outside_any_budget_visible(self, server: Any, authenticated: None) -> None:
        # It is not over budget, because there is no budget, and letting it
        # vanish from the comparison would flatter the month.
        progress = result_of(
            await server(routes(**{"/reports/budget-progress": BUDGET_PROGRESS})).call_tool("get_budget_progress", {})
        )

        assert progress["unbudgeted_spend"]["display"] == "-€50.00"


class TestEveryToolStillOnlyReads:
    """The read-only promise covers the tools added here too."""

    async def test_every_tool_says_so(self, server: Any) -> None:
        for tool in await server(routes()).list_tools():
            assert tool.annotations is not None, tool.name
            assert tool.annotations.read_only_hint is True, tool.name

UPCOMING = {
    "data": [
        {
            "name": "Rent",
            "kind": "expense",
            "amount_minor": 90_000,
            "occurs_on": "2026-10-01",
            "account_id": ACCOUNT_ID,
            "category_id": CHILD_ID,
        },
        {
            "name": "Salary",
            "kind": "income",
            "amount_minor": 250_000,
            "occurs_on": "2026-10-25",
            "account_id": ACCOUNT_ID,
            "category_id": None,
        },
    ],
    # hydra adds every kind together, whichever way the money is going.
    "total_minor": 340_000,
    "count": 2,
}


class TestUpcomingRecurring:
    """Tests for what is due next."""

    async def test_totals_only_what_is_going_out(self, server: Any, authenticated: None) -> None:
        # hydra's own total adds the salary to the rent. Quoted as one
        # unsigned figure that answers no question, and the instructions tell
        # a model to quote the display string.
        due = result_of(
            await server(routes(**{"/recurring-rules/upcoming": UPCOMING})).call_tool("get_upcoming_recurring", {})
        )

        assert due["total_leaving"]["display"] == "-€900.00"
        assert "total" not in due

    async def test_each_occurrence_carries_its_own_direction(self, server: Any, authenticated: None) -> None:
        due = result_of(
            await server(routes(**{"/recurring-rules/upcoming": UPCOMING})).call_tool("get_upcoming_recurring", {})
        )

        assert [item["amount"]["display"] for item in due["upcoming"]] == ["-€900.00", "€2500.00"]
