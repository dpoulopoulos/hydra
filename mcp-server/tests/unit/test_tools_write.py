import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from hydra_mcp.client import HydraClient
from hydra_mcp.tools import _common, register_all
from tests.conftest import TOKEN, json_response
from tests.unit.test_tools_read import ACCOUNTS, CHILD_ID, HOUSEHOLD, OTHER_ACCOUNT_ID, TREE

ACCOUNT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TRANSACTION_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def recorded_transaction(**overrides: Any) -> dict[str, Any]:
    """A transaction as hydra would report it after recording one."""
    return {
        "id": TRANSACTION_ID,
        "kind": "expense",
        "amount_minor": 4_250,
        "occurred_on": "2026-09-11",
        "account_id": ACCOUNT_ID,
        "category_id": CHILD_ID,
        "counter_account_id": None,
        "merchant": None,
        "note": None,
        "is_generated": False,
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


def writing(
    answer: dict[str, Any] | None = None, status: int = 200
) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    """Answer the reference data, and whatever is written, keeping the requests."""
    seen: list[httpx.Request] = []
    reference = {"/households/me": HOUSEHOLD, "/accounts/": ACCOUNTS, "/categories/tree": TREE}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            for path, payload in reference.items():
                if request.url.path.endswith(path):
                    return json_response(200, payload)
            return json_response(404, {"detail": "no stub"})
        return json_response(status, answer if answer is not None else {"detail": "no"})

    return handler, seen


def written(seen: list[httpx.Request]) -> dict[str, Any]:
    """The body of the one request that was not a read."""
    for request in seen:
        if request.method != "GET":
            body: dict[str, Any] = json.loads(request.content)
            return body
    raise AssertionError("nothing was written")


def sent(seen: list[httpx.Request]) -> httpx.Request:
    """The one request that was not a read."""
    for request in seen:
        if request.method != "GET":
            return request
    raise AssertionError("nothing was written")


class TestRecordExpense:
    """Tests for recording money going out."""

    async def test_sends_a_positive_amount_in_minor_units(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(recorded_transaction())

        await server(handler).call_tool(
            "record_expense",
            {"amount": "42.50", "account": "Current", "occurred_on": "2026-09-11"},
        )

        assert written(seen)["amount_minor"] == 4_250

    async def test_says_which_kind_it_is(self, server: Any, authenticated: None) -> None:
        # The direction is the tool that was called, never a sign.
        handler, seen = writing(recorded_transaction())

        await server(handler).call_tool(
            "record_expense",
            {"amount": "42.50", "account": "Current", "occurred_on": "2026-09-11"},
        )

        assert written(seen)["kind"] == "expense"

    async def test_turns_the_names_into_ids(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(recorded_transaction())

        await server(handler).call_tool(
            "record_expense",
            {
                "amount": "42.50",
                "account": "Current",
                "category": "Groceries",
                "occurred_on": "2026-09-11",
            },
        )

        body = written(seen)
        assert body["account_id"] == ACCOUNT_ID
        assert body["category_id"] == CHILD_ID

    async def test_refuses_a_negative_amount_without_asking_hydra(
        self, server: Any, authenticated: None
    ) -> None:
        handler, seen = writing(recorded_transaction())

        with pytest.raises(ToolError, match="always positive"):
            await server(handler).call_tool(
                "record_expense",
                {"amount": "-42.50", "account": "Current", "occurred_on": "2026-09-11"},
            )

        assert all(request.method == "GET" for request in seen)

    async def test_refuses_sub_cent_precision(self, server: Any, authenticated: None) -> None:
        handler, _ = writing(recorded_transaction())

        with pytest.raises(ToolError, match="2 decimal places"):
            await server(handler).call_tool(
                "record_expense",
                {"amount": "10.005", "account": "Current", "occurred_on": "2026-09-11"},
            )


class TestRecordIncome:
    """Tests for recording money coming in."""

    async def test_says_which_kind_it_is(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(recorded_transaction(kind="income"))

        await server(handler).call_tool(
            "record_income",
            {"amount": "1000.00", "account": "Current", "occurred_on": "2026-09-11"},
        )

        assert written(seen)["kind"] == "income"

    async def test_the_amount_is_still_positive(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(recorded_transaction(kind="income"))

        await server(handler).call_tool(
            "record_income",
            {"amount": "1000.00", "account": "Current", "occurred_on": "2026-09-11"},
        )

        assert written(seen)["amount_minor"] == 100_000


class TestRecordTransfer:
    """Tests for moving money between the household's own accounts."""

    async def test_names_both_ends(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(
            recorded_transaction(kind="transfer", counter_account_id=OTHER_ACCOUNT_ID, category_id=None)
        )

        await server(handler).call_tool(
            "record_transfer",
            {
                "amount": "100.00",
                "from_account": "Current",
                "to_account": "Savings",
                "occurred_on": "2026-09-11",
            },
        )

        body = written(seen)
        assert body["account_id"] == ACCOUNT_ID
        assert body["counter_account_id"] == OTHER_ACCOUNT_ID

    async def test_never_carries_a_category(self, server: Any, authenticated: None) -> None:
        # hydra has a check constraint refusing a categorised transfer, and
        # the tool takes no category at all so the model cannot try.
        handler, seen = writing(
            recorded_transaction(kind="transfer", counter_account_id=OTHER_ACCOUNT_ID, category_id=None)
        )

        await server(handler).call_tool(
            "record_transfer",
            {
                "amount": "100.00",
                "from_account": "Current",
                "to_account": "Savings",
                "occurred_on": "2026-09-11",
            },
        )

        assert "category_id" not in written(seen)


class TestUpdateTransaction:
    """Tests for changing something already recorded."""

    async def test_sends_only_what_was_given(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(recorded_transaction(merchant="The shop"))

        await server(handler).call_tool(
            "update_transaction", {"transaction_id": TRANSACTION_ID, "merchant": "The shop"}
        )

        assert written(seen) == {"merchant": "The shop"}

    async def test_patches_rather_than_replaces(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(recorded_transaction())

        await server(handler).call_tool(
            "update_transaction", {"transaction_id": TRANSACTION_ID, "amount": "50.00"}
        )

        assert sent(seen).method == "PATCH"


class TestDeleteTransaction:
    """Tests for removing something."""

    async def test_asks_hydra_to_delete_it(self, server: Any, authenticated: None) -> None:
        handler, seen = writing({"message": "Transaction deleted."})

        await server(handler).call_tool("delete_transaction", {"transaction_id": TRANSACTION_ID})

        request = sent(seen)
        assert request.method == "DELETE"
        assert request.url.path.endswith(f"/transactions/{TRANSACTION_ID}")


class TestSetBudget:
    """Tests for setting a spending limit."""

    async def test_sends_the_limit_in_minor_units(self, server: Any, authenticated: None) -> None:
        handler, seen = writing({"category_id": CHILD_ID, "month": "2026-09", "limit_minor": 40_000})

        await server(handler).call_tool(
            "set_budget", {"category": "Groceries", "limit": "400.00", "month": "2026-09"}
        )

        assert written(seen)["limit_minor"] == 40_000

    async def test_does_not_read_the_accounts_for_a_budget(self, server: Any, authenticated: None) -> None:
        # A budget has no account. Going through the whole household context
        # paged every account the household owns to build a lookup nothing
        # here consults.
        handler, seen = writing({"category_id": CHILD_ID, "month": "2026-09", "limit_minor": 40_000})

        await server(handler).call_tool(
            "set_budget", {"category": "Groceries", "limit": "400.00", "month": "2026-09"}
        )

        assert not [request for request in seen if request.url.path.endswith("/accounts/")]


class TestWhenTheTokenMayNotWrite:
    """A read token is refused by hydra, and that has to read clearly."""

    async def test_the_refusal_reaches_the_host_not_the_model(
        self, server: Any, authenticated: None
    ) -> None:
        # Retrying cannot make a read token write, so the model must not be
        # invited to try different arguments.
        handler, _ = writing({"detail": "This API token is read only and cannot change anything."}, status=403)

        with pytest.raises(MCPError, match="read only"):
            await server(handler).call_tool(
                "record_expense",
                {"amount": "42.50", "account": "Current", "occurred_on": "2026-09-11"},
            )
