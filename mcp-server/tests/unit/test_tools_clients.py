import json
from collections.abc import Callable, Iterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var
from mcp.server.auth.provider import AccessToken
from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError

from hydra_mcp import vault
from hydra_mcp.client import HydraClient
from hydra_mcp.tools import _common, register_all
from tests.conftest import TOKEN, json_response
from tests.unit.test_tools_read import ACCOUNT_ID, ACCOUNTS, HOUSEHOLD, TREE, result_of

ME = "a-user"
PIN = "246810"

# Made by the page's own code, frontend/src/lib/income-vault.ts, under PIN, at
# the cost a real vault is created with. That is what makes these tests prove
# the two sides agree rather than only that this side agrees with itself.
VAULT = {
    "user_id": ME,
    "kdf": "argon2id",
    "kdf_memory_kib": 65536,
    "kdf_iterations": 3,
    "kdf_parallelism": 1,
    "kdf_salt": "3MxLOL61OLSCL+BuNXf7gw==",
    "wrapped_dek": "csGZBvARG+J+RUedohSfwse68U1ykiQaLzTqjcqbbH6FJkhKo4vYYs/PEukp9AOYNV7V4ZlgpVRlciXF",
    "created_at": "2026-01-01T00:00:00Z",
}
MARIA_CT = "z1DmsbWBoVQyWhOIYSprKhiQrOR4JQQ8Z1yIKgJygSYupFVd1BRd9ncUy6uAXg=="  # Maria Papadopoulou
NOTE_CT = "Wolt8X983XSB/p+C11IQcdLxYfHq3J5SXJJGinlzhhOd7h/g8+LrbGNUXEE="  # Prefers mornings
# Locked by the MCP side and opened by the page's unlockVault and decryptText.
GIORGOS_CT = "kTLVH091+cLUbI1rP7MEY3e5Qj5spssMb4aiNiqCBjA/NShlxoDaiF8XNXmocA=="  # Γιώργος Ν.

MARIA_ID = "11111111-1111-1111-1111-111111111111"
GIORGOS_ID = "22222222-2222-2222-2222-222222222222"
THEIRS_ID = "33333333-3333-3333-3333-333333333333"
SESSION_ID = "44444444-4444-4444-4444-444444444444"


def a_client(client_id: str, name_ct: str, owner: str = ME, **overrides: Any) -> dict[str, Any]:
    """A client as hydra reports them."""
    return {
        "id": client_id,
        "household_id": "h",
        "owner_user_id": owner,
        "name_ct": name_ct,
        "note_ct": None,
        "cadence_frequency": None,
        "cadence_interval": 1,
        "cadence_anchor_on": None,
        "cadence_weekdays": [],
        "default_rate_minor": 6_000,
        "default_account_id": ACCOUNT_ID,
        "default_category_id": None,
        "archived_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        **overrides,
    }


CLIENTS = [
    a_client(
        MARIA_ID,
        MARIA_CT,
        note_ct=NOTE_CT,
        cadence_frequency="weekly",
        cadence_interval=2,
        cadence_anchor_on="2026-09-07",
        cadence_weekdays=[0, 3],
    ),
    a_client(GIORGOS_ID, GIORGOS_CT, archived_at="2026-06-01T00:00:00Z"),
    # Somebody else's, under a key this PIN does not open.
    a_client(THEIRS_ID, "c29tZW9uZSBlbHNlJ3MgY2lwaGVydGV4dCwgbm90IG91cnM=", owner="someone-else"),
]


def a_session(**overrides: Any) -> dict[str, Any]:
    """A session as hydra reports it."""
    return {
        "id": SESSION_ID,
        "household_id": "h",
        "client_id": MARIA_ID,
        "occurs_on": "2026-09-07",
        "fee_minor": 6_000,
        "status": "attended",
        "payment_status": "pending",
        "paid_on": None,
        "note_ct": None,
        "created_at": "2026-09-07T00:00:00Z",
        **overrides,
    }


@pytest.fixture
def authenticated() -> Iterator[None]:
    """Put a checked token on the request, the way the verifier does."""
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token=TOKEN, client_id=ME, scopes=["hydra:read"])))
    yield
    auth_context_var.reset(reset)


class Hydra:
    """Stand in for hydra's API, keeping every request made of it."""

    def __init__(self, **answers: Any) -> None:
        self.seen: list[httpx.Request] = []
        self.answers: dict[tuple[str, str], Any] = {
            ("GET", "/households/me"): HOUSEHOLD,
            ("GET", "/accounts/"): ACCOUNTS,
            ("GET", "/categories/tree"): TREE,
            ("GET", "/income/vault"): VAULT,
            ("GET", "/income/clients"): {"data": CLIENTS, "count": len(CLIENTS)},
        }
        for key, value in answers.items():
            method, _, path = key.partition(" ")
            self.answers[(method, path)] = value

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path.removeprefix("/api/v1")
        answer = self.answers.get((request.method, path))
        if answer is None:
            return json_response(404, {"detail": f"no stub for {request.method} {path}"})
        if callable(answer):
            return answer(request)
        return json_response(200, answer)

    def body_of(self, method: str, path: str) -> dict[str, Any]:
        """The body of the request made to one endpoint."""
        for request in self.seen:
            if request.method == method and request.url.path.endswith(path):
                body: dict[str, Any] = json.loads(request.content)
                return body
        raise AssertionError(f"{method} {path} was never requested")

    def query_of(self, path: str) -> dict[str, str]:
        """The query string sent to one endpoint."""
        for request in self.seen:
            if request.url.path.endswith(path):
                return dict(request.url.params)
        raise AssertionError(f"{path} was never requested")


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Callable[[Hydra], MCPServer]:
    """Build a server whose tools talk to a stand-in hydra."""

    def build(hydra: Hydra) -> MCPServer:
        monkeypatch.setattr(
            _common, "_client", HydraClient(base_url="http://hydra.test/api/v1", transport=httpx.MockTransport(hydra))
        )
        mcp: MCPServer = MCPServer("test")
        register_all(mcp)
        return mcp

    return build


async def call(mcp: MCPServer, tool: str, arguments: dict[str, Any], pin: str | None = PIN) -> Any:
    """Call a tool over a request carrying, or not carrying, the PIN header."""
    headers = {} if pin is None else {"hydra-clients-pin": pin}
    request_context: ServerRequestContext[Any, Any] = ServerRequestContext(
        session=None,  # type: ignore[arg-type]
        lifespan_context={},
        protocol_version="2025-06-18",
        method="tools/call",
        request=SimpleNamespace(headers=headers),
    )
    return await mcp.call_tool(tool, arguments, context=Context(request_context=request_context, mcp_server=mcp))


class TestKeyring:
    """The crypto has to agree with the page's, byte for byte."""

    async def test_opens_a_name_the_page_locked(self, authenticated: None) -> None:
        keys = vault.Keyring(await vault._unlock(PIN, VAULT), ME)

        assert keys.read(MARIA_CT) == "Maria Papadopoulou"
        assert keys.read(GIORGOS_CT) == "Γιώργος Ν."

    async def test_a_name_it_locks_opens_again(self) -> None:
        keys = vault.Keyring(await vault._unlock(PIN, VAULT), ME)
        locked = keys.write("Anna")

        # A fresh nonce every time, so the same name never looks the same.
        assert locked != keys.write("Anna")
        assert keys.read(locked) == "Anna"

    async def test_a_wrong_pin_is_refused_to_the_host(self) -> None:
        with pytest.raises(MCPError) as caught:
            await vault._unlock("000000", VAULT)

        assert "000000" not in str(caught.value)

    async def test_somebody_elses_name_reads_as_nothing(self) -> None:
        keys = vault.Keyring(await vault._unlock(PIN, VAULT), ME)

        assert keys.read(CLIENTS[2]["name_ct"]) is None

    async def test_the_key_is_derived_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(vault, "_unwrapped", {})
        calls: list[str] = []
        real = vault._derive

        def counting(pin: str, stored: dict[str, Any]) -> bytes:
            calls.append(pin)
            return real(pin, stored)

        monkeypatch.setattr(vault, "_derive", counting)
        await vault._unlock(PIN, VAULT)
        await vault._unlock(PIN, VAULT)

        assert len(calls) == 1

    async def test_a_locked_keyring_will_not_write(self) -> None:
        with pytest.raises(ToolError, match="Hydra-Clients-Pin"):
            vault.Keyring(None, ME).write("Anna")

    async def test_an_unknown_derivation_is_refused(self) -> None:
        with pytest.raises(ToolError, match="scrypt"):
            await vault._unlock(PIN, {**VAULT, "kdf": "scrypt"})


class TestListClients:
    """Tests for the client list."""

    async def test_opens_names_with_the_pin(self, server: Any, authenticated: None) -> None:
        listed = result_of(await call(server(Hydra()), "list_clients", {}))

        assert listed["names_unlocked"] is True
        assert [c["name"] for c in listed["clients"]] == ["Maria Papadopoulou", None]
        maria = listed["clients"][0]
        assert maria["note"] == "Prefers mornings"
        assert maria["rate"]["display"] == "€60.00"
        assert maria["account"] == "Current"
        assert maria["schedule"] == {
            "frequency": "weekly",
            "every": 2,
            "starts_on": "2026-09-07",
            "weekdays": ["monday", "thursday"],
        }

    async def test_another_members_client_has_no_name(self, server: Any, authenticated: None) -> None:
        listed = result_of(await call(server(Hydra()), "list_clients", {}))
        theirs = next(c for c in listed["clients"] if c["id"] == THEIRS_ID)

        assert theirs["name"] is None
        assert theirs["added_by_you"] is False

    async def test_archived_only_when_asked(self, server: Any, authenticated: None) -> None:
        listed = result_of(await call(server(Hydra()), "list_clients", {"include_archived": True}))

        assert "Γιώργος Ν." in [c["name"] for c in listed["clients"]]

    async def test_without_a_pin_the_figures_still_read(self, server: Any, authenticated: None) -> None:
        hydra = Hydra()
        listed = result_of(await call(server(hydra), "list_clients", {}, pin=None))

        assert listed["names_unlocked"] is False
        assert {c["name"] for c in listed["clients"]} == {None}
        # Nothing to unlock with, so the vault is not even asked for.
        assert not any(r.url.path.endswith("/income/vault") for r in hydra.seen)

    async def test_a_wrong_pin_stops_the_call(self, server: Any, authenticated: None) -> None:
        with pytest.raises(MCPError, match="did not unlock"):
            await call(server(Hydra()), "list_clients", {}, pin="999999")


class TestCreateClient:
    """Tests for adding a client."""

    async def test_locks_the_name_before_it_leaves(self, server: Any, authenticated: None) -> None:
        def created(request: httpx.Request) -> httpx.Response:
            return json_response(200, a_client(MARIA_ID, **json.loads(request.content)))

        hydra = Hydra(**{"POST /income/clients": created})
        made = result_of(
            await call(
                server(hydra),
                "create_client",
                {"name": "Anna", "account": "Current", "rate": "55.00", "note": "Tuesdays"},
            )
        )

        body = hydra.body_of("POST", "/income/clients")
        assert "Anna" not in json.dumps(body)
        assert body["default_rate_minor"] == 5_500
        assert body["default_account_id"] == ACCOUNT_ID
        # Read back through the same key, which is the page's.
        assert made["name"] == "Anna"
        assert made["note"] == "Tuesdays"

    async def test_a_schedule_is_pinned_to_a_date(self, server: Any, authenticated: None) -> None:
        def created(request: httpx.Request) -> httpx.Response:
            return json_response(200, a_client(MARIA_ID, **json.loads(request.content)))

        hydra = Hydra(**{"POST /income/clients": created})
        await call(
            server(hydra),
            "create_client",
            {
                "name": "Anna",
                "account": "Current",
                "rate": "55",
                "schedule": "weekly",
                "weekdays": ["thursday", "monday"],
            },
        )

        body = hydra.body_of("POST", "/income/clients")
        assert body["cadence_frequency"] == "weekly"
        assert body["cadence_weekdays"] == [0, 3]
        # hydra refuses a frequency with nothing to pin it to.
        assert body["cadence_anchor_on"] is not None

    async def test_days_only_go_with_a_weekly_pattern(self, server: Any, authenticated: None) -> None:
        with pytest.raises(ToolError, match="weekly"):
            await call(
                server(Hydra()),
                "create_client",
                {"name": "Anna", "account": "Current", "rate": "55", "schedule": "monthly", "weekdays": ["monday"]},
            )

    async def test_needs_the_pin(self, server: Any, authenticated: None) -> None:
        hydra = Hydra()
        with pytest.raises(ToolError) as caught:
            await call(server(hydra), "create_client", {"name": "Anna", "account": "Current", "rate": "55"}, pin=None)
        assert "Hydra-Clients-Pin" in str(caught.value)
        assert not any(r.method == "POST" for r in hydra.seen)


class TestUpdateClient:
    """Tests for changing a client."""

    async def test_finds_them_by_name_and_archives(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{f"PATCH /income/clients/{MARIA_ID}": CLIENTS[0]})
        await call(server(hydra), "update_client", {"client": "maria papadopoulou", "archived": True})

        assert hydra.body_of("PATCH", f"/income/clients/{MARIA_ID}") == {"is_archived": True}

    async def test_going_back_to_as_and_when_clears_the_schedule(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{f"PATCH /income/clients/{MARIA_ID}": CLIENTS[0]})
        await call(server(hydra), "update_client", {"client": MARIA_ID, "schedule": "none"})

        body = hydra.body_of("PATCH", f"/income/clients/{MARIA_ID}")
        assert body["cadence_frequency"] is None
        assert body["cadence_anchor_on"] is None
        assert body["cadence_weekdays"] == []

    async def test_an_empty_note_removes_it(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{f"PATCH /income/clients/{MARIA_ID}": CLIENTS[0]})
        await call(server(hydra), "update_client", {"client": MARIA_ID, "note": ""})

        assert hydra.body_of("PATCH", f"/income/clients/{MARIA_ID}") == {"note_ct": None}

    async def test_another_members_client_is_refused_to_the_model(self, server: Any, authenticated: None) -> None:
        hydra = Hydra()
        with pytest.raises(ToolError) as caught:
            await call(server(hydra), "update_client", {"client": THEIRS_ID, "archived": True})
        assert "another member" in str(caught.value)
        assert not any(r.method == "PATCH" for r in hydra.seen)

    async def test_a_near_miss_is_suggested(self, server: Any, authenticated: None) -> None:
        with pytest.raises(ToolError, match="Did you mean: Maria Papadopoulou"):
            await call(server(Hydra()), "update_client", {"client": "Maria Papadopulou", "archived": True})

    async def test_two_of_one_name_are_asked_about(self, server: Any, authenticated: None) -> None:
        twin = a_client("55555555-5555-5555-5555-555555555555", MARIA_CT)
        hydra = Hydra(**{"GET /income/clients": {"data": [*CLIENTS, twin], "count": 4}})
        with pytest.raises(ToolError) as caught:
            await call(server(hydra), "update_client", {"client": "Maria Papadopoulou", "archived": True})
        assert MARIA_ID in str(caught.value)
        assert twin["id"] in str(caught.value)

    async def test_a_name_needs_the_pin_but_an_id_does_not(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{f"PATCH /income/clients/{MARIA_ID}": CLIENTS[0]})
        mcp = server(hydra)

        with pytest.raises(ToolError) as caught:
            await call(mcp, "update_client", {"client": "Maria Papadopoulou", "archived": True}, pin=None)
        assert "Hydra-Clients-Pin" in str(caught.value)

        result_of(await call(mcp, "update_client", {"client": MARIA_ID, "archived": True}, pin=None))


class TestDeleteClient:
    """Tests for deleting a client."""

    async def test_deletes_by_name(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{f"DELETE /income/clients/{MARIA_ID}": {"message": "Client deleted."}})

        assert result_of(await call(server(hydra), "delete_client", {"client": "Maria Papadopoulou"})) == {
            "message": "Client deleted."
        }


class TestSessions:
    """Tests for the session diary."""

    async def test_lists_with_the_client_named(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(
            **{
                "GET /income/sessions": {
                    "data": [a_session()],
                    "count": 1,
                    "earned_total_minor": 6_000,
                    "outstanding_total_minor": 6_000,
                }
            }
        )
        listed = result_of(
            await call(server(hydra), "list_sessions", {"client": "Maria Papadopoulou", "owed_only": True})
        )

        assert listed["sessions"][0]["client"] == "Maria Papadopoulou"
        assert listed["owed"]["display"] == "€60.00"
        query = hydra.query_of("/income/sessions")
        assert query["client_id"] == MARIA_ID
        assert query["owed_only"] == "true"

    async def test_a_session_costs_the_clients_rate_by_default(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{"POST /income/sessions": a_session()})
        await call(server(hydra), "record_session", {"client": "Maria Papadopoulou", "on": "2026-09-14"})

        body = hydra.body_of("POST", "/income/sessions")
        assert body["fee_minor"] == 6_000
        assert body["status"] == "scheduled"
        assert body["paid_on"] is None

    async def test_paid_on_the_day_unless_told(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{"POST /income/sessions": a_session()})
        await call(
            server(hydra),
            "record_session",
            {"client": MARIA_ID, "on": "2026-09-14", "status": "attended", "payment": "paid", "fee": "70"},
        )

        body = hydra.body_of("POST", "/income/sessions")
        assert body["paid_on"] == "2026-09-14"
        assert body["fee_minor"] == 7_000

    async def test_a_payment_date_without_a_payment_is_refused(self, server: Any, authenticated: None) -> None:
        with pytest.raises(ToolError, match="payment=paid"):
            await call(
                server(Hydra()), "record_session", {"client": MARIA_ID, "on": "2026-09-14", "paid_on": "2026-09-15"}
            )

    async def test_marking_paid_sends_only_what_changed(self, server: Any, authenticated: None) -> None:
        hydra = Hydra(**{f"PATCH /income/sessions/{SESSION_ID}": a_session(payment_status="paid")})
        await call(server(hydra), "update_session", {"session": SESSION_ID, "payment": "paid"})

        assert hydra.body_of("PATCH", f"/income/sessions/{SESSION_ID}") == {"payment_status": "paid"}

    async def test_a_session_id_is_checked(self, server: Any, authenticated: None) -> None:
        with pytest.raises(ToolError, match="list_sessions"):
            await call(server(Hydra()), "delete_session", {"session": "last tuesday"})


class TestSummaryAndForecast:
    """Tests for the month's figures and the estimate."""

    async def test_summary_in_money(self, server: Any, authenticated: None) -> None:
        summary = {
            "month": "2026-09",
            "currency_code": "EUR",
            "earned_minor": 120_000,
            "received_minor": 90_000,
            "outstanding_minor": 30_000,
            "total_outstanding_minor": 45_000,
            "oldest_unpaid_on": "2026-07-01",
            "attended_count": 20,
            "unpaid_count": 5,
            "scheduled_minor": 24_000,
            "scheduled_count": 4,
            "missed_count": 1,
            "cancelled_count": 2,
            "active_client_count": 6,
            "year": 2026,
            "year_earned_minor": 900_000,
            "year_session_count": 150,
        }
        result = result_of(await call(server(Hydra(**{"GET /income/summary": summary})), "get_clients_summary", {}))

        assert result["earned"]["display"] == "€1200.00"
        assert result["owed_overall"]["display"] == "€450.00"

    async def test_forecast_names_the_clients(self, server: Any, authenticated: None) -> None:
        forecast = {
            "month": "2026-10",
            "currency_code": "EUR",
            "likely_minor": 100_000,
            "low_minor": 80_000,
            "high_minor": 120_000,
            "basis": "history",
            "months_used": 6,
            "history": [],
            "booked_minor": 24_000,
            "booked_session_count": 4,
            "earned_so_far_minor": 0,
            "expected_from_diary_minor": 20_000,
            "confidence_percent": 95,
            "active_client_count": 2,
            "priced_client_count": 2,
            "clients": [
                {
                    "client_id": MARIA_ID,
                    "name_ct": MARIA_CT,
                    "attended_count": 9,
                    "missed_count": 1,
                    "attendance_rate": 0.9,
                    "outstanding_minor": 6_000,
                    "average_monthly_minor": 24_000,
                    "booked_minor": 12_000,
                    "is_archived": False,
                }
            ],
        }
        hydra = Hydra(**{"GET /income/forecast": forecast})
        result = result_of(await call(server(hydra), "get_clients_forecast", {"months": 6}))

        assert result["likely"]["display"] == "€1000.00"
        assert result["clients"][0]["client"] == "Maria Papadopoulou"
        assert result["clients"][0]["attendance_rate"] == "90%"
        assert hydra.query_of("/income/forecast") == {"months": "6"}
