import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken

from hydra_mcp.client import HydraClient
from hydra_mcp.tools import _common, register_all
from tests.conftest import TOKEN, json_response
from tests.unit.test_tools_read import ACCOUNT_ID, ACCOUNTS, HOUSEHOLD, OTHER_ACCOUNT_ID, TREE, result_of
from tests.unit.test_tools_write import TRANSACTION_ID, recorded_transaction

GOAL_ID = "99999999-9999-9999-9999-999999999999"


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


def a_goal(**overrides: Any) -> dict[str, Any]:
    """A goal as hydra reports it."""
    return {
        "id": GOAL_ID,
        "household_id": "h",
        "account_id": OTHER_ACCOUNT_ID,
        "account_name": "Savings",
        "currency_code": "EUR",
        "name": "New car",
        "target_minor": 2_000_000,
        "target_date": "2027-12-31",
        "achieved_at": None,
        "saved_minor": 500_000,
        "peak_saved_minor": 500_000,
        "remaining_minor": 1_500_000,
        "progress": 0.25,
        "months_left": 15,
        "needed_per_month_minor": 100_000,
        "average_monthly_minor": 80_000,
        "on_track": False,
        "created_at": "2026-01-01T00:00:00Z",
        **overrides,
    }


GOALS = {
    "data": [a_goal()],
    "count": 1,
    "accounts": [
        {
            "account_id": OTHER_ACCOUNT_ID,
            "account_name": "Savings",
            "currency_code": "EUR",
            "balance_minor": 600_000,
            "assigned_minor": 500_000,
            "unassigned_minor": 100_000,
        }
    ],
}


def stubbed(answer: dict[str, Any] | None = None) -> tuple[Callable[[httpx.Request], httpx.Response], list[httpx.Request]]:
    """Answer the reads goals need, and whatever is written, keeping the requests."""
    seen: list[httpx.Request] = []
    reads = {
        "/households/me": HOUSEHOLD,
        "/accounts/": ACCOUNTS,
        "/categories/tree": TREE,
        "/goals/": GOALS,
        f"/accounts/{OTHER_ACCOUNT_ID}": ACCOUNTS["data"][1],
        f"/goals/{GOAL_ID}/history": {
            "goal_id": GOAL_ID,
            "month_from": "2026-08",
            "month_to": "2026-09",
            "months": [
                {
                    "month": "2026-09",
                    "saved_in_minor": 50_000,
                    "saved_out_minor": 0,
                    "net_minor": 50_000,
                    "cumulative_minor": 500_000,
                }
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            for path, payload in reads.items():
                if request.url.path.endswith(path):
                    return json_response(200, payload)
            return json_response(404, {"detail": f"no stub for {request.url.path}"})
        return json_response(200, answer if answer is not None else {"detail": "no"})

    return handler, seen


def written(seen: list[httpx.Request]) -> dict[str, Any]:
    """The body of the one request that was not a read."""
    for request in seen:
        if request.method != "GET":
            body: dict[str, Any] = json.loads(request.content)
            return body
    raise AssertionError("nothing was written")


class TestListGoals:
    """Tests for reading the goals."""

    async def test_describes_progress_and_pace(self, server: Any, authenticated: None) -> None:
        handler, _ = stubbed()

        listed = result_of(await server(handler).call_tool("list_goals", {}))

        [goal] = listed["goals"]
        assert goal["name"] == "New car"
        assert goal["progress"] == "25.0%"
        assert goal["needed_per_month"]["amount_minor"] == 100_000
        assert goal["on_track"] is False
        assert goal["most_saved"]["amount_minor"] == 500_000

    async def test_splits_each_account(self, server: Any, authenticated: None) -> None:
        handler, _ = stubbed()

        listed = result_of(await server(handler).call_tool("list_goals", {}))

        [account] = listed["accounts"]
        assert account["unassigned"]["amount_minor"] == 100_000


class TestGoalHistory:
    """Tests for the monthly history."""

    async def test_finds_the_goal_by_name(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed()

        history = result_of(await server(handler).call_tool("get_goal_history", {"goal": "new car"}))

        assert history["months"][0]["net"]["amount_minor"] == 50_000
        assert any(request.url.path.endswith(f"/goals/{GOAL_ID}/history") for request in seen)


class TestCreateGoal:
    """Tests for setting up a goal."""

    async def test_sends_the_target_in_minor_units(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed(a_goal())

        await server(handler).call_tool(
            "create_goal",
            {"name": "New car", "account": "Savings", "target": "20000.00", "target_date": "2027-12-31"},
        )

        assert written(seen) == {
            "name": "New car",
            "account_id": OTHER_ACCOUNT_ID,
            "target_minor": 2_000_000,
            "target_date": "2027-12-31",
        }


class TestUpdateGoal:
    """Tests for changing a goal."""

    async def test_marks_it_reached(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed(a_goal(achieved_at="2026-10-01T00:00:00Z"))

        await server(handler).call_tool("update_goal", {"goal": "New car", "reached": True})

        assert written(seen) == {"is_achieved": True}


class TestDeleteGoal:
    """Tests for removing a goal."""

    async def test_deletes_it_by_id(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed({"message": "Goal deleted."})

        await server(handler).call_tool("delete_goal", {"goal": "New car"})

        [request] = [request for request in seen if request.method != "GET"]
        assert request.method == "DELETE"
        assert request.url.path.endswith(f"/goals/{GOAL_ID}")


class TestTaggingATransfer:
    """Tests for saying which goal a transfer is for."""

    async def test_record_transfer_sends_the_goal(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed(
            recorded_transaction(kind="transfer", counter_account_id=OTHER_ACCOUNT_ID, category_id=None)
        )

        await server(handler).call_tool(
            "record_transfer",
            {
                "amount": "500.00",
                "from_account": "Current",
                "to_account": "Savings",
                "occurred_on": "2026-09-11",
                "goal": "New car",
            },
        )

        body = written(seen)
        assert body["account_id"] == ACCOUNT_ID
        assert body["goal_id"] == GOAL_ID

    async def test_update_transaction_sends_the_goal(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed(recorded_transaction(kind="transfer", counter_account_id=OTHER_ACCOUNT_ID))

        await server(handler).call_tool("update_transaction", {"transaction_id": TRANSACTION_ID, "goal": "New car"})

        assert written(seen) == {"goal_id": GOAL_ID}

    async def test_a_transfer_without_a_goal_does_not_read_them(self, server: Any, authenticated: None) -> None:
        handler, seen = stubbed(
            recorded_transaction(kind="transfer", counter_account_id=OTHER_ACCOUNT_ID, category_id=None)
        )

        await server(handler).call_tool(
            "record_transfer",
            {"amount": "1.00", "from_account": "Current", "to_account": "Savings", "occurred_on": "2026-09-11"},
        )

        assert not [request for request in seen if request.url.path.endswith("/goals/")]
