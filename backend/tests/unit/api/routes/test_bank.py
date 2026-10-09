import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_bank_connection_service,
    get_bank_sync_service,
    get_current_user,
    get_db,
    get_household_context,
    get_session_user,
)
from app.exceptions import (
    ApiTokenNotPermittedError,
    AspspNotFoundError,
    BankAccountAlreadyMappedError,
    BankAccountMappingError,
    BankAuthorizationError,
    BankConnectionInactiveError,
    BankConnectionNotFoundError,
    BankConnectionNotPermittedError,
    BankProviderError,
    BankRateLimitedError,
    BankSessionExpiredError,
    BankSyncNotConfiguredError,
)
from app.main import app
from app.models import (
    AspspPublic,
    AspspsPublic,
    BankAccountPublic,
    BankAuthorizationStarted,
    BankConnectionPublic,
    BankConnectionsPublic,
    BankConnectionStatus,
    BankStatus,
    BankSyncRunPublic,
    BankSyncStatus,
    BankSyncTrigger,
    HouseholdContext,
    Message,
    User,
)
from app.services.enable_banking import Psu

CONNECTION_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
BANK_ACCOUNT_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")


def make_bank_account() -> BankAccountPublic:
    return BankAccountPublic(id=BANK_ACCOUNT_ID, connection_id=CONNECTION_ID, name="Main", sync_enabled=True)


def make_connection() -> BankConnectionPublic:
    return BankConnectionPublic(
        id=CONNECTION_ID,
        aspsp_name="Mock ASPSP",
        aspsp_country="GR",
        status=BankConnectionStatus.ACTIVE,
        accounts=[make_bank_account()],
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def wire(mock_db_session: MagicMock, test_user: User, household_context: HouseholdContext) -> Generator[MagicMock]:
    """Override the database, the current user, the household scope and the service.

    Yields:
        A mock bank connection service the test can program.
    """
    service = MagicMock()

    def override_get_db() -> Generator[MagicMock]:
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_household_context] = lambda: household_context
    app.dependency_overrides[get_bank_connection_service] = lambda: service

    yield service

    app.dependency_overrides.clear()


class TestStatusAndAspsps:
    """Tests for GET /bank/status and GET /bank/aspsps."""

    def test_status(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.get_status.return_value = BankStatus(enabled=True)

        response = client.get("/api/v1/bank/status", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {"enabled": True}

    def test_lists_banks(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.list_aspsps.return_value = AspspsPublic(data=[AspspPublic(name="Mock ASPSP", country="GR")], count=1)

        response = client.get("/api/v1/bank/aspsps?country=GR", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["data"][0]["name"] == "Mock ASPSP"
        wire.list_aspsps.assert_called_once_with("GR")

    def test_country_must_be_two_letters(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/v1/bank/aspsps?country=GRC", headers=auth_headers)

        assert response.status_code == 422

    def test_bank_sync_off_is_a_503(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.list_aspsps.side_effect = BankSyncNotConfiguredError()

        response = client.get("/api/v1/bank/aspsps?country=GR", headers=auth_headers)

        assert response.status_code == 503
        assert "ENABLE_BANKING_APP_ID" in response.json()["detail"]


class TestStartAndComplete:
    """Tests for POST /bank/connections and POST /bank/connections/complete."""

    def test_start_returns_the_login_url_and_passes_the_psu(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.start.return_value = BankAuthorizationStarted(url="https://bank.test/login")

        response = client.post(
            "/api/v1/bank/connections",
            headers={**auth_headers, "User-Agent": "Firefox"},
            json={"aspsp_name": "Mock ASPSP", "aspsp_country": "GR"},
        )

        assert response.status_code == 200
        assert response.json() == {"url": "https://bank.test/login"}
        psu = wire.start.call_args.kwargs["psu"]
        assert isinstance(psu, Psu)
        assert psu.user_agent == "Firefox"

    def test_start_of_an_unknown_bank_is_a_400(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.start.side_effect = AspspNotFoundError("Nope", "GR")

        response = client.post(
            "/api/v1/bank/connections", headers=auth_headers, json={"aspsp_name": "Nope", "aspsp_country": "GR"}
        )

        assert response.status_code == 400

    def test_complete_returns_the_connection(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.complete.return_value = make_connection()

        response = client.post(
            "/api/v1/bank/connections/complete", headers=auth_headers, json={"code": "c", "state": "s"}
        )

        assert response.status_code == 200
        assert response.json()["accounts"][0]["name"] == "Main"

    def test_a_refused_login_is_a_400(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.complete.side_effect = BankAuthorizationError("wrong code")

        response = client.post(
            "/api/v1/bank/connections/complete", headers=auth_headers, json={"code": "c", "state": "s"}
        )

        assert response.status_code == 400
        assert "wrong code" in response.json()["detail"]


class TestConnectionsAndAccounts:
    """Tests for listing, disconnecting and linking."""

    def test_lists_connections(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.list_connections.return_value = BankConnectionsPublic(data=[make_connection()], count=1)

        response = client.get("/api/v1/bank/connections", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["count"] == 1

    def test_disconnects(self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]) -> None:
        wire.disconnect.return_value = Message(message="Bank disconnected.")

        response = client.delete(f"/api/v1/bank/connections/{CONNECTION_ID}", headers=auth_headers)

        assert response.status_code == 200
        assert wire.disconnect.call_args.kwargs["connection_id"] == CONNECTION_ID

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [(BankConnectionNotFoundError(), 404), (BankConnectionNotPermittedError(), 403)],
    )
    def test_disconnect_errors(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        error: Exception,
        status_code: int,
    ) -> None:
        wire.disconnect.side_effect = error

        response = client.delete(f"/api/v1/bank/connections/{CONNECTION_ID}", headers=auth_headers)

        assert response.status_code == status_code

    def test_links_an_account_and_only_sends_what_was_given(
        self, client: TestClient, wire: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        wire.update_bank_account.return_value = make_bank_account()

        response = client.patch(
            f"/api/v1/bank/accounts/{BANK_ACCOUNT_ID}", headers=auth_headers, json={"account_id": None}
        )

        assert response.status_code == 200
        update = wire.update_bank_account.call_args.kwargs["update"]
        assert update.model_fields_set == {"account_id"}

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [(BankAccountMappingError("currency"), 400), (BankAccountAlreadyMappedError(), 409)],
    )
    def test_link_errors(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        error: Exception,
        status_code: int,
    ) -> None:
        wire.update_bank_account.side_effect = error

        response = client.patch(f"/api/v1/bank/accounts/{BANK_ACCOUNT_ID}", headers=auth_headers, json={})

        assert response.status_code == status_code


class TestProviderErrors:
    """Tests for how the provider's errors reach the caller."""

    @pytest.mark.parametrize(
        ("error", "status_code"),
        [
            (BankProviderError("down"), 502),
            (BankSessionExpiredError(), 409),
            (BankRateLimitedError(), 429),
        ],
    )
    def test_status_codes(
        self,
        client: TestClient,
        wire: MagicMock,
        auth_headers: dict[str, str],
        error: Exception,
        status_code: int,
    ) -> None:
        wire.list_aspsps.side_effect = error

        response = client.get("/api/v1/bank/aspsps?country=GR", headers=auth_headers)

        assert response.status_code == status_code


class TestApiTokensCannotConnectBanks:
    """Tests that a machine credential cannot start, finish or end a bank login."""

    @pytest.fixture
    def wire_with_api_token(self, wire: MagicMock) -> MagicMock:
        def refuse() -> User:
            raise ApiTokenNotPermittedError

        app.dependency_overrides[get_session_user] = refuse
        return wire

    @pytest.mark.parametrize(
        ("method", "path", "body"),
        [
            ("POST", "/api/v1/bank/connections", {"aspsp_name": "Mock ASPSP", "aspsp_country": "GR"}),
            ("POST", "/api/v1/bank/connections/complete", {"code": "c", "state": "s"}),
            ("DELETE", f"/api/v1/bank/connections/{CONNECTION_ID}", None),
        ],
    )
    def test_needs_a_session(
        self,
        client: TestClient,
        wire_with_api_token: MagicMock,
        auth_headers: dict[str, str],
        method: str,
        path: str,
        body: dict[str, str] | None,
    ) -> None:
        response = client.request(method, path, headers=auth_headers, json=body)

        assert response.status_code == 403
        wire_with_api_token.start.assert_not_called()
        wire_with_api_token.complete.assert_not_called()
        wire_with_api_token.disconnect.assert_not_called()


class TestSync:
    """Tests for POST /bank/connections/{id}/sync."""

    @pytest.fixture
    def sync_service(self, wire: MagicMock) -> MagicMock:
        service = MagicMock()
        app.dependency_overrides[get_bank_sync_service] = lambda: service
        return service

    def test_syncs_as_a_present_account_holder(
        self, client: TestClient, sync_service: MagicMock, auth_headers: dict[str, str]
    ) -> None:
        sync_service.sync.return_value = BankSyncRunPublic(
            id=uuid.uuid4(),
            connection_id=CONNECTION_ID,
            trigger=BankSyncTrigger.MANUAL,
            status=BankSyncStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            fetched_count=4,
            new_count=2,
        )

        response = client.post(f"/api/v1/bank/connections/{CONNECTION_ID}/sync", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["new_count"] == 2
        kwargs = sync_service.sync.call_args.kwargs
        assert kwargs["trigger"] == BankSyncTrigger.MANUAL
        assert isinstance(kwargs["psu"], Psu)

    @pytest.mark.parametrize(
        ("error", "status_code"), [(BankConnectionNotFoundError(), 404), (BankConnectionInactiveError(), 409)]
    )
    def test_errors(
        self,
        client: TestClient,
        sync_service: MagicMock,
        auth_headers: dict[str, str],
        error: Exception,
        status_code: int,
    ) -> None:
        sync_service.sync.side_effect = error

        response = client.post(f"/api/v1/bank/connections/{CONNECTION_ID}/sync", headers=auth_headers)

        assert response.status_code == status_code

    def test_needs_a_session(self, client: TestClient, sync_service: MagicMock, auth_headers: dict[str, str]) -> None:
        def refuse() -> User:
            raise ApiTokenNotPermittedError

        app.dependency_overrides[get_session_user] = refuse

        response = client.post(f"/api/v1/bank/connections/{CONNECTION_ID}/sync", headers=auth_headers)

        assert response.status_code == 403
        sync_service.sync.assert_not_called()
