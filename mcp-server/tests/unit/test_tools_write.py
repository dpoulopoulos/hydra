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
from tests.unit.test_tools_read import (
    ACCOUNTS,
    CHILD_ID,
    DOLLAR_ACCOUNT_ID,
    HOUSEHOLD,
    MIXED_ACCOUNTS,
    OTHER_ACCOUNT_ID,
    TREE,
    result_of,
)

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
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token=TOKEN, client_id="a-user", scopes=["hydra:read"])))
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
    answer: dict[str, Any] | None = None,
    status: int = 200,
    *,
    accounts: dict[str, Any] | None = None,
    current: dict[str, Any] | None = None,
) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    """Answer the reference data, and whatever is written, keeping the requests.

    Args:
        answer: What a write is answered with.
        status: The status of that answer.
        accounts: The household's accounts, where a test needs other than the default.
        current: The transaction as it stands before an update.
    """
    seen: list[httpx.Request] = []
    reference = {
        "/households/me": HOUSEHOLD,
        "/accounts/": accounts or ACCOUNTS,
        "/categories/tree": TREE,
        f"/transactions/{TRANSACTION_ID}": current or recorded_transaction(),
    }

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

    async def test_refuses_a_negative_amount_without_asking_hydra(self, server: Any, authenticated: None) -> None:
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

    async def test_reads_the_amount_in_the_currency_of_the_account(self, server: Any, authenticated: None) -> None:
        # Not the household's: a yen account takes whole numbers, a euro one
        # takes cents, whatever the household reports in.
        yen = {
            **MIXED_ACCOUNTS,
            "data": [*MIXED_ACCOUNTS["data"][:2], {**MIXED_ACCOUNTS["data"][2], "currency_code": "JPY"}],
        }
        handler, seen = writing(recorded_transaction(account_id=DOLLAR_ACCOUNT_ID), accounts=yen)

        await server(handler).call_tool(
            "record_expense",
            {"amount": "1200", "account": "Dollars", "occurred_on": "2026-09-11"},
        )

        assert written(seen)["amount_minor"] == 1_200

    async def test_refuses_the_precision_of_the_household_currency_for_another(
        self, server: Any, authenticated: None
    ) -> None:
        yen = {
            **MIXED_ACCOUNTS,
            "data": [*MIXED_ACCOUNTS["data"][:2], {**MIXED_ACCOUNTS["data"][2], "currency_code": "JPY"}],
        }
        handler, _ = writing(recorded_transaction(), accounts=yen)

        with pytest.raises(ToolError, match="whole numbers"):
            await server(handler).call_tool(
                "record_expense",
                {"amount": "12.50", "account": "Dollars", "occurred_on": "2026-09-11"},
            )

    async def test_reports_the_amount_in_the_currency_of_the_account(self, server: Any, authenticated: None) -> None:
        handler, _ = writing(recorded_transaction(account_id=DOLLAR_ACCOUNT_ID), accounts=MIXED_ACCOUNTS)

        recorded = result_of(
            await server(handler).call_tool(
                "record_expense",
                {"amount": "42.50", "account": "Dollars", "occurred_on": "2026-09-11"},
            )
        )

        assert recorded["amount"]["display"] == "-$42.50"


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

    async def test_sends_what_arrived_when_the_currencies_differ(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(
            recorded_transaction(
                kind="transfer",
                counter_account_id=DOLLAR_ACCOUNT_ID,
                counter_amount_minor=10_842,
                category_id=None,
                amount_minor=10_000,
            ),
            accounts=MIXED_ACCOUNTS,
        )

        recorded = result_of(
            await server(handler).call_tool(
                "record_transfer",
                {
                    "amount": "100.00",
                    "amount_received": "108.42",
                    "from_account": "Current",
                    "to_account": "Dollars",
                    "occurred_on": "2026-09-11",
                },
            )
        )

        body = written(seen)
        assert body["amount_minor"] == 10_000
        assert body["counter_amount_minor"] == 10_842
        assert recorded["amount_received"]["display"] == "$108.42"

    async def test_reads_what_arrived_in_the_currency_of_the_destination(
        self, server: Any, authenticated: None
    ) -> None:
        # Yen has no cents, so 15000 is what arrived, not 150.00.
        yen = {
            **MIXED_ACCOUNTS,
            "data": [*MIXED_ACCOUNTS["data"][:2], {**MIXED_ACCOUNTS["data"][2], "currency_code": "JPY"}],
        }
        handler, seen = writing(recorded_transaction(kind="transfer"), accounts=yen)

        await server(handler).call_tool(
            "record_transfer",
            {
                "amount": "100.00",
                "amount_received": "15000",
                "from_account": "Current",
                "to_account": "Dollars",
                "occurred_on": "2026-09-11",
            },
        )

        assert written(seen)["counter_amount_minor"] == 15_000

    async def test_sends_no_amount_received_between_accounts_in_one_currency(
        self, server: Any, authenticated: None
    ) -> None:
        handler, seen = writing(recorded_transaction(kind="transfer", counter_account_id=OTHER_ACCOUNT_ID))

        await server(handler).call_tool(
            "record_transfer",
            {"amount": "100.00", "from_account": "Current", "to_account": "Savings", "occurred_on": "2026-09-11"},
        )

        assert "counter_amount_minor" not in written(seen)

    async def test_a_missing_amount_received_is_explained_by_hydra(self, server: Any, authenticated: None) -> None:
        # hydra knows which pair of accounts needs one, and says so.
        handler, _ = writing(
            {"detail": "Current holds EUR and Dollars holds USD. Say how much arrived in USD."},
            status=400,
            accounts=MIXED_ACCOUNTS,
        )

        with pytest.raises(ToolError, match="Say how much arrived"):
            await server(handler).call_tool(
                "record_transfer",
                {"amount": "100.00", "from_account": "Current", "to_account": "Dollars", "occurred_on": "2026-09-11"},
            )

    async def test_refuses_a_negative_amount_received(self, server: Any, authenticated: None) -> None:
        handler, seen = writing(accounts=MIXED_ACCOUNTS)

        with pytest.raises(ToolError, match="always positive"):
            await server(handler).call_tool(
                "record_transfer",
                {
                    "amount": "100.00",
                    "amount_received": "-108.42",
                    "from_account": "Current",
                    "to_account": "Dollars",
                    "occurred_on": "2026-09-11",
                },
            )

        assert all(request.method == "GET" for request in seen)


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

        await server(handler).call_tool("update_transaction", {"transaction_id": TRANSACTION_ID, "amount": "50.00"})

        assert sent(seen).method == "PATCH"

    async def test_reads_a_new_amount_in_the_currency_of_the_account_it_is_on(
        self, server: Any, authenticated: None
    ) -> None:
        # The transaction is on the dollar account, so that is the currency
        # the new amount is turned into minor units in.
        current = recorded_transaction(account_id=DOLLAR_ACCOUNT_ID)
        handler, seen = writing(current, accounts=MIXED_ACCOUNTS, current=current)

        await server(handler).call_tool("update_transaction", {"transaction_id": TRANSACTION_ID, "amount": "50.00"})

        assert written(seen) == {"amount_minor": 5_000}

    async def test_a_new_account_decides_the_currency_of_a_new_amount(self, server: Any, authenticated: None) -> None:
        yen = {
            **MIXED_ACCOUNTS,
            "data": [*MIXED_ACCOUNTS["data"][:2], {**MIXED_ACCOUNTS["data"][2], "currency_code": "JPY"}],
        }
        handler, _ = writing(accounts=yen)

        with pytest.raises(ToolError, match="whole numbers"):
            await server(handler).call_tool(
                "update_transaction",
                {"transaction_id": TRANSACTION_ID, "amount": "50.50", "account": "Dollars"},
            )

    async def test_changes_what_arrived(self, server: Any, authenticated: None) -> None:
        current = recorded_transaction(
            kind="transfer",
            counter_account_id=DOLLAR_ACCOUNT_ID,
            counter_amount_minor=10_842,
            category_id=None,
        )
        handler, seen = writing(current, accounts=MIXED_ACCOUNTS, current=current)

        await server(handler).call_tool(
            "update_transaction", {"transaction_id": TRANSACTION_ID, "amount_received": "109.00"}
        )

        assert written(seen) == {"counter_amount_minor": 10_900}

    async def test_only_a_transfer_has_an_amount_received(self, server: Any, authenticated: None) -> None:
        handler, seen = writing()

        with pytest.raises(ToolError, match="Only a transfer"):
            await server(handler).call_tool(
                "update_transaction", {"transaction_id": TRANSACTION_ID, "amount_received": "109.00"}
            )

        assert all(request.method == "GET" for request in seen)

    async def test_does_not_read_the_transaction_for_a_change_without_an_amount(
        self, server: Any, authenticated: None
    ) -> None:
        handler, seen = writing(recorded_transaction(merchant="The shop"))

        await server(handler).call_tool(
            "update_transaction", {"transaction_id": TRANSACTION_ID, "merchant": "The shop"}
        )

        assert not [r for r in seen if r.url.path.endswith(f"/transactions/{TRANSACTION_ID}") and r.method == "GET"]


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

        await server(handler).call_tool("set_budget", {"category": "Groceries", "limit": "400.00", "month": "2026-09"})

        assert written(seen)["limit_minor"] == 40_000

    async def test_does_not_read_the_accounts_for_a_budget(self, server: Any, authenticated: None) -> None:
        # A budget has no account. Going through the whole household context
        # paged every account the household owns to build a lookup nothing
        # here consults.
        handler, seen = writing({"category_id": CHILD_ID, "month": "2026-09", "limit_minor": 40_000})

        await server(handler).call_tool("set_budget", {"category": "Groceries", "limit": "400.00", "month": "2026-09"})

        assert not [request for request in seen if request.url.path.endswith("/accounts/")]


class TestWhenTheTokenMayNotWrite:
    """A read token is refused by hydra, and that has to read clearly."""

    async def test_the_refusal_reaches_the_host_not_the_model(self, server: Any, authenticated: None) -> None:
        # Retrying cannot make a read token write, so the model must not be
        # invited to try different arguments.
        handler, _ = writing({"detail": "This API token is read only and cannot change anything."}, status=403)

        with pytest.raises(MCPError, match="read only"):
            await server(handler).call_tool(
                "record_expense",
                {"amount": "42.50", "account": "Current", "occurred_on": "2026-09-11"},
            )
